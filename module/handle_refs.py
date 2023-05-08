import re
import logging

from module.constants import RefTypes, APP_NAME, SLOGGER_NAME, FLOGGER_NAME

log = logging.getLogger(APP_NAME)
# Logging to console
slog = logging.getLogger(SLOGGER_NAME)
# Logging to files
flog = logging.getLogger(FLOGGER_NAME)


class InputRefKeys:
    # Meaningful input reference keys for AMS Batch MR Lookup query
    AUTHOR = ("author",)
    TITLE = ("title", "maintitle")
    JOURNAL = ("journal", "journaltitle", "fjournal", "booktitle")
    VOLUME = ("volume",)
    ISSUE = ("number", "series")
    PAGES = ("pages",)
    YEAR = ("year", "date")
    ISSN = ("issn", "isrn", "isbn")

    # For the best AMD DB search results
    # query string should be constructed in the following order
    KEYS_IN_ORDER = [
        AUTHOR,
        TITLE,
        JOURNAL,
        VOLUME,
        ISSUE,
        PAGES,
        YEAR,
        ISSN
    ]

RE_KEY_VALUE = re.compile(r"^\s*([\w-]+)\s*=\s*(.*?)$", re.DOTALL)

RE_LINEEND = re.compile(r'(\r?\n)+')
RE_PAR = re.compile(r'(\r?\n){2}')

RE_BIBL_ENV = re.compile(r'\s*\\(?P<envstatus>begin|end)\s*'
                         r'{(thebibliography|biblist\*?)}(.*)$')

RE_BIBRE = re.compile(r'^\s*\\bibitem.*')
RE_BIBREF = re.compile(r'\s*\\bibitem\s*(?P<biblabel>\[.*?\])*?\s?'
                       r'{(?P<citekey>.*?)}(?P<text>.*)$', re.S)
RE_BIBTEX = re.compile(r'^\s*(@\S+)(?<!@preamble)\s*'
                       r'{(?P<citekey>\S+)\s*,(?P<text>.*)$', re.M)
RE_AMSREFS = re.compile(r"\\bib\s*{(?P<citekey>.*)}\s*{(.*)}\s*{(?P<text>.*)$",
                        re.M)


class RefHandler(object):
    """ This class unites methods and attributes related to bibliography
        reference format types and their content modifications """

    def __init__(self, outputtype):
        """ Initiate reference handling methods and attributes

            Parameters
            ----------
            outputtype : str or None
                Required reference output format type
        """

        self.outputtype = outputtype

    @staticmethod
    def find_reference(line):
        """ Identify reference environment or element by using regex patterns

            Parameters
            ----------
            line : str

            Returns
            -------
            str or None
                If match is found, returns the reference type, None otherwise
            dict
                Dictionary contains regex pattern group names and their matches

                The value of the key 'text' is the line part without user
                defined strings, such as citekey and biblabel, because they may
                contain some misleading information for BatchMRef query
        """

        elems = {RefTypes.BiblEnv.ENV: RE_BIBL_ENV,
                 RefTypes.BIBTEX: RE_BIBTEX,
                 RefTypes.AMSREFS: RE_AMSREFS}

        # BIBITEM search starts with an additional check
        # which other reference types doesn't have
        if RE_BIBRE.search(line) is not None:
            elems = {RefTypes.BIBITEM: RE_BIBREF}

        for reftype, pattern in elems.items():
            match = pattern.search(line)
            if match is not None:
                return reftype, match.groupdict()
            elif reftype == RefTypes.BIBITEM:
                # If final search for BIBITEM fails, it means that the typical
                # structure for this reference type is placed on several lines,
                # therefore the current line is prepended to the next input line
                return reftype, {"line": line}
        return None, dict()

    @staticmethod
    def extract_keys_data(lines):
        """ Extract values from selected keys in reference

            Parameters
            ----------
            lines : list

            Returns
            -------
            str
                Output contains extracted values separated by commas
        """
        flog.debug(">> Extracting key values from reference")
        ref_data = dict()
        current_key_index = None
        current_user_key = None
        for line in lines:
            if not line.strip('\n\t "{},'):
                continue
            # found new key with the value or
            # only its continuing value on the next line:
            match = RE_KEY_VALUE.search(line)
            if match:
                user_key, user_value = match.groups()
                user_key = user_key.lower()
                indices = [index for index, keys
                           in enumerate(InputRefKeys.KEYS_IN_ORDER)
                           if user_key in keys]
                if indices:
                    current_key_index = indices[0]
                    part_of_qstring = "{}, ".format(
                        user_value.strip('\n\t "{},')
                    )
                    # adding value only if key was not found previously
                    # or the same key repeated multiple times
                    if current_key_index not in ref_data:
                        ref_data[current_key_index] = part_of_qstring
                        current_user_key = user_key
                    elif user_key == current_user_key:
                        ref_data[current_key_index] += part_of_qstring
                    else:
                        current_key_index = None
                        current_user_key = None
                else:
                    current_key_index = None
                    current_user_key = None

            elif current_key_index is not None:
                # adding continuing value
                part_of_qstring = "{} {}, ".format(
                    ref_data.get(current_key_index, "").strip(", "),
                    line.strip('\n\t "{},')
                    )
                ref_data[current_key_index] = part_of_qstring

        # sorting found values according to InputRefKeys.KEYS_IN_ORDER:
        querystring = ""
        for key, value in sorted(ref_data.items()):
            querystring += value
        return querystring.strip(", ")

    @staticmethod
    def insert_mrid(reftype, refstring, mrid):
        """ Format MR number according to the input reference format and
            append it to the input reference

            Parameters
            ----------
            reftype : str
                Determined input bibliography reference item type
            refstring : str
                Input bibliography reference item content
            mrid : str
                MR number returned by query to BatchMRef

            Returns
            -------
            str
                Output contains input bibliography reference element including
                according to reftype formatted mrid.
        """
        properties = RefTypes.ITYPES.get(reftype, None)
        if properties is None:
            outstring = RE_LINEEND.sub('\n', refstring)
            return f'{outstring}\\MR{{{mrid}}}\n\n'

        mr_string = properties.MR_FORMAT.format(mrid)
        ending_index = refstring.rfind(properties.REF_ENDING)
        if ending_index == -1:
            paragraph = RE_PAR.search(refstring)
            if paragraph is not None:
                ending_index = paragraph.start()
                mr_string += "\n"

        if ending_index != -1:
            return "{}{}{}".format(
                refstring[:ending_index].strip('\n\t ,'),
                mr_string,
                refstring[ending_index:].lstrip()
                )

        return refstring.strip() + mr_string + "\n"

    def insert_citekey(self, outref, citekey, biblabel, querystring):
        """ Add a cite key, extracted from an input reference item,
            to the reference content, returned by the query to BatchMRef
            (XML tag <outref>), in the required reference output format

            Parameters
            ----------
            outref : str or None
                Reference item content returned by the query to BatchMRef
            citekey : str
                Input bibliography reference item cite key
            biblabel : str or None
                Input bibliography reference item label,
                provided in optional parameter of reference type of BIBITEM
            querystring : str
                Input bibliography reference item formatted for query
                to BatchMRef

            Returns
            -------
            str or None
                Returned string is the outref including the citekey and
                the biblabel (if provided) if reference has been found in
                the AMS MR DB, else string is formatted according to the
                requested output type.

                If allowed output type is not provided, None is returned
        """

        if self.outputtype is None:
            return None

        if outref is None:
            if self.outputtype == RefTypes.TEX:
                return f"\\bibitem{biblabel if biblabel is not None else ''}" \
                       f"{{{citekey}}}\n   Not Found!\n\n"

            if self.outputtype == RefTypes.BIBTEX:
                return f'@MISC {{{citekey},\n   NOTE = {{Not Found!}}\n}}\n\n'
            if self.outputtype == RefTypes.IMS:
                return (f'@MISC {{{citekey},\n   '
                        f'HOWPUBLISHED = {{{querystring}}},\n}}\n\n')
            if self.outputtype == RefTypes.AMSREFS:
                return (f'\\bib{{{citekey}}}{{misc}}'
                        f'{{\n    note = {{Not Found!}}\n}}\n\n')
            if self.outputtype == RefTypes.HTML:
                return f'<!-- {citekey} -->\nNot Found!\n<br/><br/>\n\n'
            return None

        outref = outref.strip() + '\n\n'
        if self.outputtype == RefTypes.TEX:
            return (f'\\bibitem{biblabel if biblabel is not None else ""}'
                    f'{{{citekey}}}\n{outref}')
        if self.outputtype in [RefTypes.BIBTEX, RefTypes.IMS]:
            return RE_BIBTEX.sub(r'\1 {%s,' % citekey, outref)
        if self.outputtype == RefTypes.AMSREFS:
            return RE_AMSREFS.sub(r'\\bib\0{%s}{\2}' % citekey, outref)
        if self.outputtype == RefTypes.HTML:
            return f'<!-- {citekey} -->\n{outref}<br/><br/>\n'
        return None


class RefElement(object):
    """ This is a container for one bibliography reference item,
        containing all data related to it """

    def __init__(self, refid=None, reftype=None, citekey=None, biblabel=None,
                 orig_mrid=False):
        """ Initiate reference item container

            Parameters
            ----------
            refid : int or None
            reftype : str or None
                Input bibliography reference type (one of RefTypes.ITYPES).
            citekey : str or None
                Input bibliography reference cite key
            biblabel : str or None
                Input bibliography reference label,
                provided in the optional parameter of RefTypes.BIBITEM type
                reference item
            orig_mrid : int or None
                Input bibliography reference MR number,
                found in input before query to DB
        """

        self.reftype = reftype
        self.refid = refid
        self.citekey = citekey
        self.biblabel = biblabel
        self.orig_mrid = orig_mrid

        self.orig_lines = list()
        self.cleaned_lines = list()
        self.query_lines = list()
        self.comment_lines = list()

        self.errno = None
        self._init_querystring = None
        self._querystring = None
        self._mrid = None
        self.outref = None

    def normalize(self, lines):
        """ Normalize the reference item content
            Parameters
            ----------
            lines : list

            Returns
            -------
            str
                Returned string doesn't contain trailing spaces and
                typical ending for the reference of reftype (if found)
        """
        new_string = re.sub(r'\s+', ' ', ''.join(lines)).strip()
        if self.reftype in RefTypes.ITYPES:
            ending_str = RefTypes.ITYPES[self.reftype].REF_ENDING
            ending_index = new_string.rfind(ending_str)
            if ending_index != -1:
                new_string = new_string[:ending_index].strip()
        return new_string

    @property
    def init_querystring(self):
        if self._init_querystring is not None:
            return self._init_querystring

        flog.debug(">> Normalizing the reference")
        self._init_querystring = self.normalize(self.query_lines)

        return self._init_querystring

    @property
    def querystring(self):
        if self._querystring is not None:
            return self._querystring
        return self.init_querystring

    @querystring.setter
    def querystring(self, istring):
        self._querystring = istring

    @property
    def mrid(self):
        return self._mrid

    @mrid.setter
    def mrid(self, mrid):
        """ Normalize MR number, returned by the query to BatchMRef

            Parameters
            ----------
            mrid : str

            Returns
            -------
            str
                If original MR number is shorter than 7 symbols, prepending 0,
                till it reaches 7 symbol length
        """
        if mrid is not None:
            self._mrid = mrid.lstrip("MR").rjust(7, '0')

    def __repr__(self):
        result = f"<{self.__class__.__name__}:\n"
        for key, value in sorted(self.__dict__.items()):
            if key.startswith("_"):
                continue
            result += f"     {key} = {repr(value)}\n"
        result += "     >\n"
        return result

    def __str__(self):
        return self.__repr__()


class RefsContainer(object):
    """ This is a container holding as many bibliography reference items as
        is allowed by the denoted query to BatchMRef limit and data common
        to all of them """

    def __init__(self):
        super(RefsContainer, self).__init__()
        self.elems = list()
        self.qerrno = None

    def append_elem(self, ref_element):
        """ Add bibliography reference item instance to the container

            Parameters
            ----------
            ref_element : RefElement() instance
        """

        self.elems += (ref_element,)

    def get_elem_by_refid(self, refid):
        """ Get bibliography reference item instance by its id

            Parameters
            ----------
            refid : int

            Returns
            -------
            RefElement() instance or None
                If element with required id is not found, None is returned
        """

        elem = [e for e in self.elems if e.refid == refid]
        if elem:
            return elem[0]

    def __str__(self):
        result = f"<{self.__class__.__name__}:\n"
        for key, value in sorted(self.__dict__.items()):
            if key == "elems":
                for elem in value:
                    result += f"  {repr(elem)}"
            elif key not in ["elems", "qresult", "xml"]:
                result += f"  GLOBAL: {key} = {value}\n"
        result += "  >\n"
        return result
