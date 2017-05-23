#! /usr/bin/env python
# -*- coding: utf-8 -*-
##################################################################################
#
#  getmref.py - gets the references links to MathSciNet throught the BatchMRef:
#                                 http://www.ams.org/batchref?qdata=xmldocument
#
#  Copyright (C) 2017 Sigitas Tolusis, VTeX Ltd., Jim Pitman, Dept. Statistics,
#  U.C. Berkeley and Lolita Tolene, VTeX Ltd.
#  E-mail: latex-support@vtex.lt
#  http://www.stat.berkeley.edu/users/pitman
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  Requires:
#    - python ver. >=2.2
#    - [ for option --enc=auto ]
#      Universal Encoding Detector library, written by Mark Pilgrim.
#
#  Usage:
#    getmref.py <bbl or tex file>
#
#  Program (description):
#    - makes inputfile copy to <inputfilename>.getmref.bak;
#    - for each successful bibitem reference search adds line \MR{<mrid>},
#      where <mrid> is data from XML tag <mrid> without front symbols "MR";
#    - writes all adds to <inputfilename>;
#    - generates log file <inputfilename>.getmref.log;
#    - writes to stdout log info
#
#  Changes:
#    2004/04/26 - \bibitem line removed from the query
#    2017/01/12 - input file may contain 'amsrefs', 'bibtex' and 'tex' type
#                 references (all at once);
#                 input references can be formatted as 'amsrefs', 'bibtex',
#                 'tex' or 'html' type references
#
#
##################################################################################

__version__ = "GetMRef, v2.3.1"

import sys
import os
import re
import string
import urllib
import urllib2
import shutil
import logging
from time import time, sleep
from xml.dom.minidom import parseString
from xml.parsers.expat import ExpatError

BASICFORMATTER = logging.Formatter('%(message)s')
DEBUGFORMATTER = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())
flog = slog = log


class RefTypes(object):
    """ This class declares recognized bibliography reference formats

        Formats description
        -------------------
        Source: only AMS
        "tex": LaTeX code without any specific beginning/ending;
               MR number is given in plain text
        "html": <a href="http://www.ams.org/mathscinet-getitem?mr=7digits">
                    7digits
                </a>

        Source: only user
        "bibitem": \bibitem[<name-year info>]{<cite_key>}
                       ...
                   \MR{<7 digits>}
                   \endbibitem,
                   where '[<name-year info>]' and '\endbibitem' are optional
                   Requires environment
                       \begin{thebibliography}{<ref no>}
                           ...
                       \end{thebibliography}

        Source: AMS and user
        "bibtex": @<ref type>{<cite_key>,
                      <key1>={<value1>},
                      <key2>={<value2>},
                      MRNUMBER={<7 digits>}
                      ...}
        "amsrefs": \bib{<cite_key>}{<ref type>}{
                       <key1>={<value1>},
                       <key2>={<value2>},
                       review={\MR{<7 digits>}}
                       ...}
                   Requires environment
                       \begin{biblist}
                           ...
                       \end{biblist}
    """

    TEX = "tex"
    BIBITEM = "bibitem"
    IMS = "ims"
    BIBTEX = "bibtex"
    AMSREFS = "amsrefs"
    HTML = "html"

    # Reference input formats
    ITYPES = (BIBITEM, BIBTEX, AMSREFS)

    # Reference output formats
    OTYPES = (TEX, BIBTEX, IMS, AMSREFS, HTML)


class LessThanFilter(logging.Filter):
    """ This class allows to add an upper bound to the logged messages

        Example
        -------
        One needs to log all non-error messages to stdout, and all errors
        (higher level) only to stderr
    """

    def __init__(self, exclusive_maximum, name=""):
        super(LessThanFilter, self).__init__(name)
        self.max_level = exclusive_maximum

    def filter(self, record):
        # A non-zero return means we log this message
        return 1 if record.levelno <= self.max_level else 0


class FilesHandler(RefTypes):
    """ This class unites methods and attributes related to
        files I/O actions """

    IN = 'in'
    BAK = 'bak'
    OUT = 'out'
    DATA = 'data'
    TMP = 'tmp'
    AUX = 'aux'
    BIB = 'bib'
    HTML = 'html'
    LOG = 'log'
    ERR = 'err'

    # File status map:
    #   if True file will be open until closed;
    #   if False it will be opened on demand
    FILE_STATUS = {OUT: True,
                   LOG: False,
                   ERR: False,
                   DATA: True,
                   BIB: True,
                   AUX: True,
                   HTML: True,
                   TMP: False}

    READ = 'r'
    WRITE = 'w'

    GMR_SUFFIX = 'getmref'

    def __init__(self, infile, outputtype):
        """ Initiate file handling methods and attributes

            Parameters
            ----------
            infile : str or None
                Path to input file
            outputtype : str or None
                Required bibliography reference output format type
        """

        self.infile = infile
        self._basename = os.path.splitext(infile)[0]

        # Determining needed file types for given reference output type
        msg = ("The given references will be formatted in '%s' format. "
               % (outputtype if outputtype is not None else "orig"))

        unnecessary = [self.DATA, self.BIB, self.AUX, self.HTML]
        if outputtype in [self.BIBTEX, self.IMS]:
            unnecessary = [self.DATA, self.HTML]
            # Referring to 'BIB' file as 'DATA'
            self.DATA = self.BIB
            msg += "Additional files will be created: *.%s, *.%s" \
                   % (self.BIB, self.AUX)
        elif outputtype == self.HTML:
            unnecessary = [self.DATA, self.BIB, self.AUX]
            # Referring to 'HTML' file as 'DATA'
            self.DATA = self.HTML
            msg += "Additional file will be created: *.%s" % self.HTML
        elif outputtype in [self.TEX, self.AMSREFS]:
            unnecessary = [self.HTML, self.BIB, self.AUX]
            msg += "Additional file will be created: *.%s" % self.DATA

        self.files = dict()
        for suffix, status in self.FILE_STATUS.items():
            # Deleting old files
            self._delete(suffix)
            if suffix in unnecessary:
                continue
            if status:
                self.open(suffix)
                continue
            self.files.update({suffix: self.get_fname(suffix)})

        flog.info("File: %s" % infile)
        if not (os.path.isfile(infile) and os.path.exists(infile)):
            logging.shutdown()
            for suffix in self.FILE_STATUS:
                self.close_and_delete(suffix)
            raise ValueError("Provided source file does not exist! "
                             "Please provide the valid one.")

        flog.debug("Workdir: %s" % os.path.abspath(os.path.dirname(infile)))
        flog.debug(msg)

    def set_fname(self, suffix):
        """ Set a filepath for a file with the provided suffix

            Parameters
            ----------
            suffix : str
                File suffix without punctuation

            Returns
            -------
            str
        """
        return ("%s.%s.%s" % (self._basename, self.GMR_SUFFIX, suffix)
                if suffix != self.IN else self.infile)

    def get_fname(self, suffix):
        """ Get filepath of a file with the required suffix

            Parameters
            ----------
            suffix : str
                File suffix without punctuation

            Returns
            -------
            str
                If requested file is open, returning file object name,
                or the filepath otherwise
        """
        target = self.files.get(suffix, self.set_fname(suffix))
        if isinstance(target, file):
            return target.name
        return target

    def open(self, suffix, mask=WRITE):
        """ Open file for the selected action

            Parameters
            ----------
            suffix : str
                File suffix without punctuation
            mask : str
                Possible actions are read or write

            File is opened and file object is added to the dictionary
            for later access
        """
        self.files.update({suffix: file(self.get_fname(suffix), mask)})

    def read(self, suffix):
        """ Get the content of a file with the required suffix

            Parameters
            ----------
            suffix : str
                File suffix without punctuation

            Yields
            ------
            str
        """
        with open(self.get_fname(suffix), self.READ) as ifile:
            for iline in ifile:
                yield iline

    def write(self, suffix, msg):
        """ Write to the file with the required suffix
            only if this file is open

            Parameters
            ----------
            suffix : str
                File suffix without punctuation
            msg : str
        """
        target = self.files.get(suffix, None)
        if isinstance(target, file):
            target.write(msg)

    def close(self, suffix):
        """ Close the file with the required suffix

            Parameters
            ----------
            suffix : str
                File suffix without punctuation
        """
        fileobj = self.files.get(suffix, "")
        if isinstance(fileobj, file):
            fileobj.close()

    def _delete(self, suffix):
        """ Delete the file with the required suffix

            Parameters
            ----------
            suffix : str
                File suffix without punctuation
        """
        dfile = self.get_fname(suffix)
        try:
            os.unlink(dfile)
            flog.debug("Deleted: %s" % os.path.split(dfile)[1])
        except OSError:
            if os.path.isfile(dfile) and os.path.exists(dfile):
                flog.exception("Can't remove file: %s" % dfile)

    def close_and_delete(self, suffix):
        """ Close and delete the file with the required suffix

            Parameters
            ----------
            suffix : str
                File suffix without punctuation
        """
        self.close(suffix)
        self._delete(suffix)

    def close_files(self):
        """ Close all open files and logging instances,
            create backup of the input file and
            overwrite it with the new content, delete auxiliary files
        """
        flog.debug("Closing files...")
        for suffix in self.files:
            self.close(suffix)

        self._delete(self.TMP)

        bfile = self.get_fname(self.BAK)
        if os.path.exists(bfile):
            shutil.copy2(self.infile, bfile)
        else:
            os.rename(self.infile, bfile)
        flog.debug("Created backup of the input file: %s"
                   % os.path.split(bfile)[1])

        ofile = self.get_fname(self.OUT)
        if os.path.exists(ofile):
            shutil.copy2(ofile, self.infile)
            self._delete(self.OUT)
        else:
            os.rename(ofile, self.infile)
        flog.debug("The input file is overwritten with: %s"
                   % os.path.split(ofile)[1])

        logging.shutdown()


class RefHandler(RefTypes):
    """ This class unites methods and attributes related to bibliography
        reference format types and their content modifications """

    # Bibliography environment
    BIBL_ENV = "environment"
    BIBL_BEGIN = "begin"
    BIBL_END = "end"

    # Declaration of typical reference type ending and
    # MR id format for this type
    FORMAT_PROPERTIES = {
        RefTypes.BIBTEX: {
            "ref_ending": "}",
            "mr_format": ",\nMRNUMBER={%s},\n"
            },
        RefTypes.AMSREFS: {
            "ref_ending": "}",
            "mr_format": ",\nreview={\MR{%s}},\n"
            },
        RefTypes.BIBITEM: {
            "ref_ending": "\\endbibitem",
            "mr_format": "\n\\MR{%s}\n"
            }
        }

    # Meaningful reference keys for AMS Batch MR Lookup query
    KEYS = {"0AUTH": ("author",),
            "1TTL": ("title", "maintitle"),
            "2JOUR": ("journal", "journaltitle", "fjournal", "booktitle"),
            "3VID": ("volume",),
            "4IID": ("number", "series"),
            "5PID": ("pages",),
            "6YNO": ("year", "date"),
            "7ISSN": ("issn", "isrn", "isbn")}

    PATTERN_KEY_VALUE = "^\s*([\w-]+)\s*=\s*(.*?)$"

    PATTERN_LINE_END = r'(\r?\n)+'
    PATTERN_PAR = r'(\r?\n){2}'

    PATTERN_BIBL_ENV = (r'\s*\\(?P<envstatus>begin|end)\s*'
                        r'\{(thebibliography|biblist\*?)\}(.*)$')

    PATTERN_BIBRE = r'^\s*\\bibitem.*'
    PATTERN_BIBREF = (r'\s*\\bibitem\s*(?P<biblabel>\[.*?\])*?\s?'
                      r'\{(?P<citekey>.*?)\}(?P<text>.*)$')
    PATTERN_BIBTEX = (r'^\s*(@\S+)(?<!@preamble)\s*'
                      r'{(?P<citekey>\S+)\s*,(?P<text>.*)$')
    PATTERN_AMSREFS = r"\\bib\s*{(?P<citekey>.*)}\s*{(.*)}\s*{(?P<text>.*)$"

    def __init__(self, outputtype):
        """ Initiate reference handling methods and attributes

            Parameters
            ----------
            outputtype : str or None
                Required reference output format type
        """

        self.outputtype = outputtype

        self.re_bibl_env = re.compile(self.PATTERN_BIBL_ENV)
        self.re_bibre = re.compile(self.PATTERN_BIBRE)
        self.re_bibreF = re.compile(self.PATTERN_BIBREF, re.S)
        self.re_bibtex = re.compile(self.PATTERN_BIBTEX, re.M)
        self.re_amsrefs = re.compile(self.PATTERN_AMSREFS, re.M)

        self.re_lineend = re.compile(self.PATTERN_LINE_END)
        self.re_par = re.compile(self.PATTERN_PAR)
        self.re_key_value = re.compile(self.PATTERN_KEY_VALUE, re.DOTALL)

    def find_reference(self, line):
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

        elems = {self.BIBL_ENV: self.re_bibl_env,
                 self.BIBTEX: self.re_bibtex,
                 self.AMSREFS: self.re_amsrefs}

        # BIBITEM search starts with an additional check
        # which other reference types doesn't have
        if self.re_bibre.search(line) is not None:
            elems = {self.BIBITEM: self.re_bibreF}

        for reftype, pattern in elems.items():
            match = pattern.search(line)
            if match is not None:
                return reftype, match.groupdict()
            elif reftype == self.BIBITEM:
                # If final search for BIBITEM fails, it means that the typical
                # structure for this reference type is placed on several lines,
                # therefore the current line is prepended to the next input line
                return reftype, {"line": line}
        return None, dict()

    def extract_keys_data(self, lines):
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
        querystring = ""
        user_key = None
        found = list()
        for line in lines:
            match = self.re_key_value.search(line)
            if match:
                user_key, user_value = match.groups()
                user_key = user_key.lower()
                for key, value in sorted(self.KEYS.items()):
                    if user_key in value and (user_key in found or key not in found):
                        found.append(key)
                        found.append(user_key)
                        querystring += "%s, " % user_value.strip().rstrip(",")\
                                                          .strip().strip('"')\
                                                          .strip().rstrip("}")\
                                                          .lstrip("{").strip()
                        break
            elif len(found) > 0 and found[-1] == user_key:
                querystring = "%s %s, " % (querystring.strip(", "),
                                           line.strip().rstrip(",").strip().strip('"')
                                               .strip().rstrip("}").lstrip("{")
                                               .strip().rstrip(",").strip())

        return querystring.strip(", ")

    def insert_mrid(self, reftype, refstring, mrid):
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
        properties = self.FORMAT_PROPERTIES.get(reftype, None)
        if properties is None:
            outstring = self.re_lineend.sub('\n', refstring)
            return '%s\\MR{%s}\n\n' % (outstring, mrid)

        mr_string = properties["mr_format"] % mrid
        ending_index = refstring.rfind(properties["ref_ending"])
        if ending_index == -1:
            paragraph = self.re_par.search(refstring)
            if paragraph is not None:
                ending_index = paragraph.start()
                mr_string += "\n"

        if ending_index != -1:
            return "%s%s%s" % (refstring[:ending_index].strip().strip(","),
                               mr_string,
                               refstring[ending_index:].lstrip())

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
            if self.outputtype == self.TEX:
                return ("\\bibitem%s{%s}\n   Not Found!\n\n"
                        % (biblabel if biblabel is not None else "",
                           citekey))
            if self.outputtype == self.BIBTEX:
                return '@MISC {%s,\n   NOTE = {Not Found!}\n}\n\n' % citekey
            if self.outputtype == self.IMS:
                return ('@MISC {%s,\n   HOWPUBLISHED = {%s},\n}\n\n'
                        % (citekey, querystring))
            if self.outputtype == self.AMSREFS:
                return ('\\bib{%s}{misc}{\n    note = {Not Found!}\n}\n\n'
                        % citekey)
            if self.outputtype == self.HTML:
                return '<!-- %s -->\nNot Found!\n<br/><br/>\n\n' % citekey
            return None

        outref = outref.strip() + '\n\n'
        if self.outputtype == self.TEX:
            return ('\\bibitem%s{%s}\n%s'
                    % (biblabel if biblabel is not None else "",
                       citekey, outref))
        if self.outputtype in [self.BIBTEX, self.IMS]:
            return self.re_bibtex.sub(r'\1 {%s,' % citekey, outref)
        if self.outputtype == self.AMSREFS:
            return self.re_amsrefs.sub(r'\\bib\0{%s}{\2}' % citekey, outref)
        if self.outputtype == self.HTML:
            return '<!-- %s -->\n%s<br/><br/>\n' % (citekey, outref)
        return None


class RefElement(object):
    """ This is a container for one bibliography reference item,
        containing all data related to it """

    FORMAT_PROPERTIES = RefHandler.FORMAT_PROPERTIES

    def __init__(self, refid=None, reftype=None, citekey=None, biblabel=None):
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
        """

        self.reftype = reftype
        self.refid = refid
        self.citekey = citekey
        self.biblabel = biblabel

        self.orig_lines = list()
        self.cleaned_lines = list()
        self.query_lines = list()
        self.comment_lines = list()

        self.errno = 0
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
        nstring = re.sub('\s+', ' ', ''.join(lines)).strip()
        ending = self.FORMAT_PROPERTIES.get(self.reftype,
                                            dict()).get("ref_ending", "")
        ending_index = nstring.rfind(ending)
        if ending_index != -1:
            nstring = nstring[:ending_index].strip()
        return nstring

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
            self._mrid = mrid.encode('ascii').lstrip("MR").rjust(7, '0')

    def __repr__(self):
        result = "<%s:\n" % self.__class__.__name__
        for key, value in sorted(self.__dict__.items()):
            if key.startswith("_"):
                continue
            result += "     %s = %s\n" % (key, repr(value))
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
        self.qerrno = 0

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
        result = "<%s:\n" % self.__class__.__name__
        for key, value in sorted(self.__dict__.items()):
            if key == "elems":
                for elem in value:
                    result += "  %s" % repr(elem)
            elif key not in ["elems", "qresult", "xml"]:
                result += "  GLOBAL: {} = {}\n".format(key, value)
        result += "  >\n"
        return result


class QueryHandler(RefTypes):
    """ This class unites methods and attributes related to actions necessary
        for the AMS BatchMRef query """

    AUTO_ENC = "auto"
    LATIN1 = 'latin1'
    ASCII = "ascii"

    AMS_URL = 'http://www.ams.org/batchmref'

    # AMS BatchMRef limit of items no per query
    QUERY_ITEMS_LIMIT = 100

    QUERY_XML_HEADING_STRING = '<?xml version="1.0" encoding="UTF-8"?>\n'

    QUERY_HEADING_STRING = (
        '<mref_batch>\n'
        ' %s'
        '</mref_batch>'
        )

    QUERY_ITEM_STRING = (
        '<mref_item outtype="%s">\n'
        ' <inref>\n'
        '  %s\n'
        ' </inref>\n'
        ' <myid>%d</myid>\n'
        '</mref_item>\n'
        )

    QUERY_FORMATS = {
        RefTypes.TEX: RefTypes.TEX,
        RefTypes.BIBTEX: RefTypes.BIBTEX,
        RefTypes.IMS: RefTypes.BIBTEX,
        RefTypes.AMSREFS: RefTypes.AMSREFS,
        RefTypes.HTML: RefTypes.HTML,
        None: RefTypes.TEX
        }

    PATTERN_MREF_ITEM = '(\<mref_item outtype="(?:bibtex|tex|amsrefs|html)"\>.*?\</mref_item\>)'
    PATTERN_BATCH_ERROR = '\<batch_error\>(.*?)\</batch_error\>'

    # AMS gives the following message in HTML if requested website is broken
    AMS_MSG = "The AMS Website is temporarily unavailable."

    def __init__(self, encoding, outputtype, refscontainer, address=AMS_URL):
        """ Initiate query to BatchMRef handling methods and attributes

            Parameters
            ----------
            encoding : str
                Input file encoding
            outputtype : str or None
                Reference output format type passed for BatchMRef query
            refscontainer : RefsContainer() instance
            address : str
                BatchMRef query address
        """

        self.encoding = encoding
        flog.debug("Provided encoding format: %s" % encoding)
        self.address = address
        self.query_format = self.QUERY_FORMATS.get(outputtype, self.TEX)
        flog.debug("Query settings: URL = %s, output format = %s"
                   % (address, self.query_format))
        self.outputtype = outputtype

        self.errno = 0
        self.qresult = None
        self.qcode = None
        self.xml = None
        self.re_mref_item = re.compile(self.PATTERN_MREF_ITEM, re.DOTALL)
        self.re_batch_error = re.compile(self.PATTERN_BATCH_ERROR, re.DOTALL)

        self._refscontainer = refscontainer
        self.query_elems = list()

    @property
    def refscontainer(self):
        return self._refscontainer

    def _encode_str(self, istring):
        """ Change query string encoding into the ASCII

            Parameters
            ----------
            istring : str

            Returns
            -------
            str
        """

        str_enc = self.encoding
        self.errno = 0
        if str_enc == self.AUTO_ENC:
            detector = UniversalDetector()
            detector.feed(istring)
            detector.close()
            str_enc = detector.result.get('encoding', self.ASCII)
            flog.debug(">> Determined string encoding: %s" % str_enc)

        if str_enc == self.ASCII:
            return istring
        if str_enc is None:
            flog.debug(">> Encoding determination has FAILED! ")
            return istring

        try:
            return istring.decode(str_enc.lower()).encode(self.ASCII,
                                                          errors='replace')
        except:
            flog.debug(">> encoding given reference element FAILED!")
            msg = (">> encoding given reference element FAILED!\n"
                   "[Input string]:\n%s\n" % istring)
            flog.exception(msg)
            self.errno = -2
            return istring

    @staticmethod
    def _escape_tex(istring):
        """ Convert TeX symbols into XML valid symbols

            Parameters
            ----------
            istring : str

            Returns
            -------
            str
        """

        flog.debug(">> Converting TeX symbols into XML valid symbols")
        return reduce(lambda a, b: string.replace(a, b[0], b[1]),
                      (istring, ("\\&", '&amp;'), ("<", '&lt;'), (">", '&gt;'),
                                ("&", '&amp;'), (r"\ndash ", "-")))

    def _parse_str(self, istring, check=False):
        """ Parse string into XML object

            Parameters
            ----------
            istring : str
            check : bool
                If True, checking if string parses to valid XML.
                If False, saving parsed XML or an error code
                if parsing was unsuccessful
        """

        try:
            xml = parseString(istring)
            if not check:
                self.xml = xml
            else:
                flog.debug("VALIDATING XML string ...")
            flog.debug(">> XML contains no errors")
        except ExpatError as err:
            flog.debug(">> Parsing given XML FAILED!")
            msg = (">> Parsing given XML FAILED!\n",
                   "[Parse query]:\n%s\n" % istring)
            flog.exception(msg)
            self.errno = err.code

    def prepare_query_str(self, refid, querystring):
        """ Format the reference as an XML string and validate it

            Parameters
            ----------
            refid : int
                RefElement() instance id
            querystring : str

            Returns
            -------
            int
                If query string was encoded and parsed into valid XML
                successfully, it is appended to a future query strings list
                and error code is set to 0

                If something went wrong, non-zero value is returned
        """

        self.errno = 0
        flog.debug("PREPARING query reference")

        single_qstring = self._encode_str(
            self.QUERY_ITEM_STRING % (self.query_format,
                                      self._escape_tex(querystring),
                                      refid)
            )
        flog.debug(">> Formed query XML:\n"
                   + "~" * 70 + "\n%s\n" % single_qstring + "~" * 70)

        # Checking if formed string is a valid XML
        self._parse_str(single_qstring, check=True)
        if self.errno != 0:
            return self.errno

        self.query_elems.append(single_qstring)
        return self.errno

    def _send_query(self, querystring):
        """ Send query to BatchMRef

            Parameters
            ----------
            querystring : str
                Validated XML query string, containing as many reference items
                as QueryHandler.QUERY_ITEMS_LIMIT allows

            If request to BatchMRef was successful, saving query result,
            otherwise non-zero error code is saved
        """

        queryinfo = {'qdata': querystring}
        queryval = urllib.urlencode(queryinfo)
        try:
            flog.debug("SENDING query ...")
            req = urllib2.Request(url=self.address, data=queryval)
            flog.debug(">> Query POST data: %s" % req.get_data())
            batchmref = urllib2.urlopen(req)
            self.qcode = batchmref.getcode()
            flog.debug(">> Query result code: %s" % self.qcode)
            self.qresult = batchmref.read()

            if self.qcode == 200 and \
                    self.qresult.startswith(self.QUERY_XML_HEADING_STRING):
                flog.debug(">> Query result string:\n"
                           + "~"*70 + "\n%s\n" % self.qresult.strip() + "~"*70)
            else:
                msg = "\n%s" % self.AMS_MSG if self.AMS_MSG in self.qresult else ""
                flog.debug(">> Query FAILED! %s" % msg)
                flog.error("Query returned an error:\n%s\n\n%s"
                           % (msg, self.qresult))
                self.errno = self.qcode if self.qcode != 200 else -2
                self.qresult = None

            batchmref.close()
        except:
            msg = ">> Query FAILED!"
            flog.debug(msg)
            flog.exception(msg)
            self.errno = -2
            self.qresult = None

    @staticmethod
    def _extract_xml_data(xml_elem, tag):
        """ Extract text data from an XML object

            Parameters
            ----------
            xml_elem : XML object
            tag : str
                XML tag of interest

            Returns
            -------
            str or None
                Content of XML element with the requested tag.
                If element with the tag hasn't been found, None is returned
        """

        childelem = xml_elem.getElementsByTagName(tag)
        if childelem:
            childnodes = childelem[0].childNodes
            if childnodes:
                return childnodes[0].data

    def _analyze_xml(self, xml):
        """ Extract reference data from the BatchMRef returned XML string,
            parsed into XML object

            Parameters
            ----------
            xml : XML object

            If no matches have been found in the AMS MR DB,
            current RefElement() instance gets a non-zero error code.
            Otherwise MR number and reference content (if requested output type
            is not None) are saved in the current RefElement() instance
        """

        mref_item = xml.getElementsByTagName("mref_item")[0]
        refid = int(self._extract_xml_data(mref_item, "myid"))
        elem = self.refscontainer.get_elem_by_refid(refid)

        matches = self._extract_xml_data(mref_item, "matches")
        if matches == '1':
            flog.debug(">> MRef DB: reference `%s' found!" % elem.citekey)
            elem.mrid = self._extract_xml_data(mref_item, "mrid")
            flog.debug(">> MRef ID: %s" % elem.mrid)

            if self.outputtype is not None:
                elem.outref = self._extract_xml_data(mref_item, "outref")
                flog.debug(">> MRef output reference:\n"
                           + "~"*70 + "\n%s\n" % elem.outref.strip() + "~"*70)
        else:
            elem.errno = -1
            flog.debug(">> MRef DB: reference `%s' not found!" % elem.citekey)

    def query(self):
        """ Send a request to AMS BatchMRef and analyze the returned data

            If query result contains 'batch_error' element or returned
            XML string can't be parsed into XML object,
            RefsContainer() instance gets a non-zero error code.
        """

        self.errno = 0
        self.qresult = None

        querystring = (self.QUERY_XML_HEADING_STRING
                       + self.QUERY_HEADING_STRING % ("\n".join(self.query_elems)))
        if self.errno == 0:
            self._send_query(querystring)
            if self.qresult is not None:
                error_obj = self.re_batch_error.search(self.qresult)
                if error_obj:
                    flog.debug(">> Query XML contains an ERROR!")
                    flog.error("[batch_error]:\n%s\n\n[querystring]:\n%s"
                               % (self._encode_str(error_obj.group(1)),
                                  querystring))
                    self.errno = -2
                flog.debug("Splitting query result and analyzing parts separately")
                for item_qresult in self.re_mref_item.finditer(self.qresult):
                    self.xml = None
                    self._parse_str(self._encode_str(item_qresult.group()))
                    if self.xml is not None:
                        self._analyze_xml(self.xml)

        self.refscontainer.qerrno = self.errno
        self.query_elems = list()


class HandleBBL(RefTypes):
    """ This is the main class containing and initiating other classes'
        methods and attributes for provided input data processing """

    # MR number pattern matching all recognized reference formats
    PATTERN_MR = r'MRNUMBER=\{.*?\}(,|)|review=\{\\MR\{.*?\}\}(,|)|\\MR\{.*?\}'

    PATTERN_BIBRE_LINE = r'^%.*\r?\n$'
    PATTERN_BIBRE_PART = r'\s*(.*?)(?<!\\)%.*\r?\n$'

    PATTERN_TEX_ACCENTS = r"""(?:\{|)\\(?:"|'|`|\^|-|H|~|c|k|=|b|\.|d|r|u|v|A)(?:|\{)([a-zA-Z])\}(?:\}|)"""
    PATTERN_BRACED_LETTERS = r"""(\s)(?<!\\)([a-zA-Z]*)\{([A-Z]+)\}"""

    # Mark of the input file ending
    EOF = "EOF"

    # Default bibstyle format
    PLAIN = 'plain'

    def __init__(self, inputfile, encoding, clean_comments,
                 itemno, wait, outputtype, bibstyle, debug, version=str()):
        """ Initiate all methods and attributes required to process input data

            Parameters
            ----------
            inputfile : str or None
            encoding : str
                Input file encoding
            clean_comments : bool
                If TeX comments cleaning is selected,
                full comment lines will be moved to the beginning of each
                identified bibliography reference item
            itemno : int
                Limit of reference items per query to BatchMRef
            wait: int
                Pause length after each query to BatchMRef
            outputtype : str or None
                If not None, additional files with the requested references,
                extracted from the AMS MR DB in the requested output format,
                will be generated
            bibstyle : str or None
                Used only if the requested output type is BIBTEX or IMS
            debug : int
                If debug value is greater than 0, debug messages will be
                written to the FileHandler.LOG file.  Also, depending on the
                given debug value, final data written to the input file will
                contain TeX comments with query data.
            version : str
        """

        self.refscontainer = RefsContainer()

        self.fh = FilesHandler(inputfile, outputtype)
        self.rh = RefHandler(outputtype)
        self.qh = QueryHandler(encoding, outputtype, self.refscontainer)

        if itemno < self.qh.QUERY_ITEMS_LIMIT:
            self.qh.QUERY_ITEMS_LIMIT = itemno
        self.wait = wait

        self.outputtype = outputtype
        self.bibstyle = bibstyle
        flog.debug("Comments will be cleaned from the output: %s"
                   % clean_comments)
        self.clean_comments = clean_comments
        self.debug = debug
        self.version = version

        self.re_bibre_line = re.compile(self.PATTERN_BIBRE_LINE)
        self.re_bibre_part = re.compile(self.PATTERN_BIBRE_PART)
        self.re_MR = re.compile(self.PATTERN_MR)
        self.re_tex_accents = re.compile(self.PATTERN_TEX_ACCENTS)
        self.re_braced_letters = re.compile(self.PATTERN_BRACED_LETTERS)

        self.eof = False
        self.ifile_end_lines = list()

    @property
    def icontent(self):
        """ Input file content """
        return self.fh.read(self.fh.IN)

    @property
    def write(self):
        return self.fh.write

    @property
    def get_fname(self):
        return self.fh.get_fname

    def preprocess_ofiles(self):
        """ Depending on the requested bibliography output type,
            certain files are pre-filled with required data.
            Writing action is fulfilled only if requested file was pre-opened.
        """
        self.write(self.fh.AUX, '\\bibstyle{%s}\n' % self.bibstyle)
        self.write(self.fh.HTML, "<!DOCTYPE html>\n<html>\n<body>\n\n")

    def postprocess_ofiles(self, refcount):
        """ Depending on the requested bibliography output type,
            certain files are filled up with the required data.
            Writing action is fulfilled only if requested file was pre-opened.

            Parameters
            ----------
            refcount: int
                If refcount is 0, it means no references have been found
                in the input file, and pre-opened additional files are deleted

            If requested bibliography output type is TEX,
            number of bibliography items found is written to the first line of
            FileHandler.DATA file.  Therefore this file is written twice into.
        """

        if refcount == 0:
            self.fh.close_and_delete(self.fh.DATA)
            self.fh.close_and_delete(self.fh.AUX)
            return None

        datafilepath = self.get_fname(self.fh.DATA)
        self.write(self.fh.AUX,
                   '\\bibdata{%s}' % os.path.splitext(datafilepath)[0])
        self.write(self.fh.HTML, "\n</body>\n</html>\n")

        # Formatting the DATA file output according to requested output format
        obiblenv = {
            self.TEX: {
                "begin": "\\begin{thebibliography}{%s}\n"
                          "\\csname bibmessage\\endcsname\n\n",
                "end": "\\end{thebibliography}\n"
                },
            self.AMSREFS: {
                "begin": "\\begin{bibdiv}\n\\begin{biblist}\n\n",
                "end": "\\end{biblist}\n\\end{bibdiv}"
                }
            }

        strings = obiblenv.get(self.outputtype, None)
        if strings is None:
            return None

        start_string, finish_string = sorted(strings.values())
        self.write(self.fh.DATA, finish_string)

        # Total items count is known only after processing all references and
        # writing to the DATA file, therefore 'thebibliography' environment
        # starting string is written to this file when all processing is
        # finished
        self.fh.close(self.fh.DATA)
        os.rename(datafilepath, self.get_fname(self.fh.TMP))
        self.fh.open(self.fh.TMP, self.fh.READ)

        if self.outputtype == self.TEX:
            start_string = start_string % refcount
        self.fh.open(self.fh.DATA, self.fh.WRITE)
        self.write(self.fh.DATA, start_string)

        shutil.copyfileobj(self.fh.files[self.fh.TMP],
                           self.fh.files[self.fh.DATA])

    def _remove_tex_comments(self, line):
        """ Remove TeX comments

            Parameters
            ----------
            line : str

            Returns
            -------
            str
        """
        fmtline = self.re_bibre_line.sub('', line)
        if fmtline:
            matchobj = self.re_bibre_part.search(fmtline)
            if matchobj is not None:
                return "%s\n" % matchobj.groups(1)[0]
            return fmtline
        return fmtline

    def _remove_tex_accents(self, line):
        """ Remove TeX accents and braces around upper case letters

            BatchMRef may not found a reference in the AMS MR DB because of
            braces and accents present in reference string (tested), therefore
            accented letters "{\'a}" and "\'{a}" are changed to plain "a".
            Also "{ABC}" is changed to "ABC".

            Parameters
            ----------
            line : str

            Returns
            -------
            str
        """
        mline = self.re_tex_accents.sub(r'\1', line)
        if mline:
            return self.re_braced_letters.sub(r'\1\2\3', mline)
        return mline

    def gather_records(self, require_env):
        """ Extract bibliography reference items from the input file

            Parameters
            ----------
            require_env : bool
                If True, get bibliography reference items only inside
                the bibliography environment.  If False, gel all bibliography
                reference items found in the input file

            Yields
            -------
            str
                Denotes reference format type (one of ITYPES),
                bibliography environment state (RefHandler.BIBL_BEGIN or
                RefHandler.BIBL_END),
                or input file end mark (EOF)

            RefElement() instance, str, or None
                If reference of one of ITYPES type has been found,
                a RefElement() instance is returned with the following
                attributes filled in:
                reftype, citekey, biblabel,
                orig_lines, cleaned_lines, query_lines

                If end of input file has been determined, None is returned

                Otherwise current line is returned
        """

        def sort_comments_out(comment_lines):
            """ Assign gathered comment lines to the rightful reference item

                Parameters
                ----------
                comment_lines : list

                Returns
                -------
                list
                    Comment lines, belonging to current reference item
                list
                    Comment lines, belonging to the next reference item
            """

            next_elem_comments = []
            reversed_comments = comment_lines[::-1]
            reversed_comments_backup = comment_lines[::-1]
            advanced_by = 0
            for no, cline in enumerate(reversed_comments):
                if len(element.orig_lines) < (no + 1 + advanced_by):
                    break
                while not element.orig_lines[-(no + 1 + advanced_by)].strip():
                    # skipping empty lines
                    advanced_by += 1
                if cline == element.orig_lines[-(no + 1 + advanced_by)]:
                    reversed_comments_backup.pop(0)
                    next_elem_comments.append(reversed_comments[no])
            current_elem_comments = reversed_comments_backup[::-1]
            return current_elem_comments, next_elem_comments

        # Allowing gathering the references according to
        # the bibliography environment status
        envmap = {self.rh.BIBL_BEGIN: True,
                  self.rh.BIBL_END: False,
                  "not found": False if require_env else True}
        gather = envmap["not found"]
        search = True

        multiline = ""
        element = RefElement()
        envstatus = None
        for line in self.icontent:
            line = multiline + line
            clean_line = self._remove_tex_comments(line)

            if not clean_line and element.orig_lines:
                element.orig_lines.append(line)
                element.comment_lines.append(line)
                continue

            reftype = None
            if search:
                reftype, additional_info = self.rh.find_reference(clean_line)

            if require_env and reftype == self.rh.BIBL_ENV:
                if element.reftype is not None:
                    # Full bibliography item
                    element.comment_lines, next_elem_comments = \
                        sort_comments_out(element.comment_lines)
                    yield element.reftype, element
                    element = RefElement()
                    element.comment_lines = next_elem_comments

                # Bibliography environment
                envstatus = additional_info.pop("envstatus", None)
                if envstatus in envmap:
                    gather = envmap[envstatus]
                    search = gather
                    yield envstatus, line
                    continue

            elif reftype in self.ITYPES:
                multiline = additional_info.get("line", "")
                if multiline:
                    continue

                if element.reftype is not None:
                    # Full bibliography item
                    element.comment_lines, next_elem_comments = \
                        sort_comments_out(element.comment_lines)
                    yield element.reftype, element
                    element = RefElement()
                    element.comment_lines = next_elem_comments

                if gather:
                    element.reftype = reftype
                    element.citekey = additional_info.get("citekey", None)
                    element.biblabel = additional_info.get("biblabel", None)
                    element.orig_lines.append(line)

                    mrid_free_line = self.re_MR.sub('', clean_line)
                    element.cleaned_lines.append(mrid_free_line)

                    ref_format_free_line = additional_info.get("text", clean_line)
                    mrid_free_line = self.re_MR.sub('', ref_format_free_line)
                    accent_free_line = self._remove_tex_accents(mrid_free_line)
                    element.query_lines.append(accent_free_line)
                    continue

            if gather and element.reftype is not None:
                element.orig_lines.append(line)
                mrid_free_line = self.re_MR.sub('', clean_line)
                element.cleaned_lines.append(mrid_free_line)
                accent_free_line = self._remove_tex_accents(mrid_free_line)
                element.query_lines.append(accent_free_line)
            else:
                # Before and after the bibliography environment
                yield envstatus, line

        if element.reftype is not None:
            # The last full bibliography item
            element.comment_lines, _ = sort_comments_out(element.comment_lines)
            yield element.reftype, element

        yield self.EOF, None

    def transfer_to_file(self):
        """ After each query to BatchMRef write gathered data into files

            Returns
            -------
            int
                Number of references, for which data has been successfully
                obtained
        """

        successful = 0

        for elem in self.refscontainer.elems:
            if self.refscontainer.qerrno != 0:
                elem.errno = self.refscontainer.qerrno
            outstring = ''.join(elem.cleaned_lines if self.clean_comments else
                                elem.orig_lines)

            elem.outref = self.rh.insert_citekey(
                elem.outref, elem.citekey, elem.biblabel,
                elem.normalize(elem.cleaned_lines[1:]))
            if elem.mrid is not None:
                outstring = self.rh.insert_mrid(elem.reftype, outstring, elem.mrid)
                slog.info(elem.mrid)
            elif elem.errno == -1:
                slog.warn('NotFound')
            else:
                slog.error('QueryError')

            if self.clean_comments:
                outstring = "".join(elem.comment_lines) + outstring

            if self.debug == 1:
                outstring = '%%%% %s\n%s' % (elem.querystring, outstring)
            elif self.debug == 2:
                outstring = '%%%% %s\n%s' % (elem.errno, outstring)
            elif self.debug == 3:
                outstring = '%%%% %s\n%%%% %s\n%s' % (elem.querystring,
                                                      elem.errno,
                                                      outstring)

            flog.debug("\n" + ">" * 70
                       + "\nFINAL reference with MR id in original format:\n"
                       + "\n%s\n" % outstring.strip())

            if elem.outref is not None:
                flog.debug("FINAL reference in '%s' format:\n" % self.outputtype
                           + "\n%s\n" % elem.outref.strip() + "<" * 70)
            self.write(self.fh.OUT, outstring)
            self.write(self.fh.DATA, elem.outref if elem.outref else "")
            self.write(self.fh.AUX, '\\citation{%s}\n' % elem.citekey)

            if elem.errno == 0 and self.refscontainer.qerrno == 0:
                successful += 1

        if self.eof:
            while self.ifile_end_lines:
                self.write(self.fh.OUT, self.ifile_end_lines.pop(0))

        self.refscontainer = RefsContainer()
        self.qh._refscontainer = self.refscontainer

        return successful

    def get_mr_codes(self, require_env):
        """ Analyze input file content and process found reference items

            Parameters
            ----------
            require_env : bool
                If True, and if no bibliography reference items have been found
                inside the bibliography environment, or an environment hasn't
                been found at all, parameter is set to False this method and
                reruns itself in order to search reference items in
                the whole input file.

            Returns
            -------
            int
                Total bibliography reference items found
            int
                Total number of references, for which data has been
                successfully obtained
            int
                Reference items processed with errors count

            If reference item of ITYPES has been found, current
            RefElement() instance attribute 'refid' is assigned a value
        """

        msg = ("in the bibliography environment only"
               if require_env else "in the whole input file")
        flog.debug("SEARCHING for reference items: %s" % msg)

        total = 0
        valid = 0
        successful = 0
        records = self.gather_records(require_env=require_env)
        pseudo_citekey = 0
        for reftype, record in records:
            if reftype == self.EOF:
                self.eof = True

            elif reftype not in self.ITYPES:
                if reftype != self.rh.BIBL_END:
                    self.write(self.fh.OUT, record)
                else:
                    self.ifile_end_lines.append(record)
                continue

            elif valid == 0 or valid % self.qh.QUERY_ITEMS_LIMIT != 0:
                total += 1

                record.refid = total
                if not record.citekey:
                    pseudo_citekey += 1
                    record.citekey = '%s' % pseudo_citekey

                flog.debug("=" * 70)
                flog.debug("FOUND reference %s: type=%s, cite_key=%s, biblabel=%s"
                           % (total, reftype, record.citekey, record.biblabel))

                if reftype != self.BIBITEM:
                    record.querystring = self.rh.extract_keys_data(record.query_lines)
                self.refscontainer.append_elem(record)
                record.errno = self.qh.prepare_query_str(record.refid,
                                                         record.querystring)
                if record.errno == 0:
                    valid += 1

            if valid != 0 and (valid % self.qh.QUERY_ITEMS_LIMIT == 0
                               or self.eof):
                self.qh.query()
                successful += self.transfer_to_file()
                valid = 0
                if not self.eof:
                    sleep(self.wait)

        if total == 0 and require_env:
            # If no bibliography items were found in the bibliography
            # environment, then trying to search for them everywhere
            # in the input file
            flog.debug("FOUND no references! Changing the search mode ... ")
            self.eof = False
            self.ifile_end_lines = list()
            self.fh.close(self.fh.OUT)
            self.fh.open(self.fh.OUT)
            return self.get_mr_codes(require_env=False)

        if self.ifile_end_lines:
            self.transfer_to_file()

        flog.debug("=" * 70)
        errors = total - successful
        return total, successful, errors

    def run(self, require_env):
        """ Main method

            Parameters
            ----------
            require_env : bool

            Returns
            -------
            get_mr_codes() output
        """

        slog.info("# %s #\nJob started:" % self.version)
        starttime = time()

        self.preprocess_ofiles()
        total, successful, errors = self.get_mr_codes(require_env=require_env)
        self.postprocess_ofiles(refcount=total)

        flog.info("   total: %s, found: %s, not found: %s, time: %ss"
                  % (total, successful, errors, int(round(time()-starttime))))

        slog.info("Job ended")
        slog.info("Total: %s, found: %s, not found: %s"
                  % (total, successful, errors))
        slog.info('Job completed in %ss' % int(round(time()-starttime)))

        self.fh.close_files()
        return total, successful, errors


if __name__ == '__main__':
    import argparse

    # Logging to console
    osh = logging.StreamHandler(stream=sys.stdout)
    osh.setFormatter(BASICFORMATTER)
    osh.setLevel(logging.INFO)
    osh.addFilter(LessThanFilter(logging.INFO))

    esh = logging.StreamHandler(stream=sys.stderr)
    esh.setFormatter(BASICFORMATTER)
    esh.setLevel(logging.WARN)

    slog = logging.getLogger("%s.StreamLogger" % __name__)
    slog.setLevel(logging.INFO)
    slog.addHandler(osh)
    slog.addHandler(esh)

    # Logging to files
    flog = logging.getLogger("%s.FileLogger" % __name__)
    flog.setLevel(logging.DEBUG)

    def setup_logging_files(debug, basename=""):
        """ Set up logging files

            Parameters
            ----------
            debug : int
            basename: str
                Input file name

            Returns
            -------
            logging instance
        """

        if debug == 0:
            log_min_level = logging.INFO
            log_max_level = logging.INFO
            formatter = BASICFORMATTER
        else:
            log_min_level = logging.DEBUG
            log_max_level = logging.WARN
            formatter = DEBUGFORMATTER

        ofh = logging.FileHandler(filename="{}.{}.{}".format(basename,
                                                             FilesHandler.GMR_SUFFIX,
                                                             FilesHandler.LOG),
                                  mode='w', delay=True)
        ofh.setFormatter(formatter)
        ofh.setLevel(log_min_level)
        ofh.addFilter(LessThanFilter(log_max_level))
        flog.addHandler(ofh)

        efh = logging.FileHandler(filename="{}.{}.{}".format(basename,
                                                             FilesHandler.GMR_SUFFIX,
                                                             FilesHandler.ERR),
                                  mode='w', delay=True)
        efh.setFormatter(DEBUGFORMATTER)
        efh.setLevel(logging.ERROR)
        flog.addHandler(efh)
        return flog

    VERSION = __version__.split("-")[0]
    DESCRIPTION = (
        "Tool %s, is designed for: " % VERSION
        + "(1) getting MR numbers for given references from AMS MRef database, "
        + "(2) formatting the given references in one of AMS allowed formats. "
        + "Maintainer: L.Tolene <lolita.tolene@vtex.lt>."
    )

    def get_cmd_args():
        """ Command line input parser """

        parser = argparse.ArgumentParser(
            description=DESCRIPTION,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        parser.add_argument("filepath", help="References containing file")
        parser.add_argument(
            "--enc", '-e', type=str, default=QueryHandler.LATIN1,
            help="Source file encoding or 'auto'"
        )
        parser.add_argument(
            "--format", '-f', choices=set(RefTypes.OTYPES),
            help="Outputs the given references in provided format.  "
                 "For more information about these formats please "
                 "consult the AMS MRef tool website.  The 'ims' format "
                 "is almost the same as the 'bibtex' format"
        )
        parser.add_argument(
            "--bibstyle", '-s',  default=HandleBBL.PLAIN,
            help="BibTeX style.  For more information please consult "
                 "the BibTeX documentation"
        )
        parser.add_argument(
            "--nobibenv", action='store_true',
            help="If activated, references are searched throughout "
                 "all source file content; otherwise searching only "
                 "inside the bibliography environment.  Currently "
                 "recognizable are the 'thebibliography' and 'biblist' "
                 "environments"
        )
        parser.add_argument(
            "--clean", '-c', action='store_true',
            help="If activated, cleans comments appearing in references"
        )
        parser.add_argument(
            "--itemno", default=100, type=int,
            help="Maximum item count for one AMS query. "
                 "AMS batchmref has a limit of 100 items per query."
        )
        parser.add_argument(
            "--wait", default=10, type=int,
            help="time (in seconds) to wait between queries to AMS batchmref."
        )
        parser.add_argument(
            "--debug", '-d', choices={0, 1, 2, 3}, default=0, type=int,
            help="Outputs additional info for debugging purposes."
        )
        parser.add_argument(
            "--version", '-v', action='version', version=VERSION,
            help="Module version."
        )
        args = parser.parse_args()
        return (args.filepath, args.enc, args.format, args.bibstyle,
                args.nobibenv, args.clean, args.itemno, args.wait, args.debug)

    # Get input parameter values
    inputfile, encoding, output_format, bibstyle, nobibenv, clean, itemno, wait, debug \
        = get_cmd_args()

    # Load additional library is needed
    if encoding == QueryHandler.AUTO_ENC:
        from chardet.universaldetector import UniversalDetector

    # Setup logging files
    flog = setup_logging_files(debug=debug,
                               basename=os.path.splitext(inputfile)[0])

    # Create HandleBBL() instance
    bblobj = HandleBBL(inputfile=inputfile, encoding=encoding,
                       clean_comments=clean, itemno=itemno, wait=wait,
                       outputtype=output_format, bibstyle=bibstyle,
                       debug=debug, version=VERSION)

    # Process input file
    bblobj.run(require_env=not nobibenv)
