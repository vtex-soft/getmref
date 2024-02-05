import logging
import os
import re
import time

from module.constants import \
    Ext, RefTypes, QUERY_ITEMS_LIMIT, APP_NAME, SLOGGER_NAME, FLOGGER_NAME
from module.handle_logging import StatisticsData
from module.handle_files import FilesHandler, FileMask, EOF
from module.handle_refs import RefsContainer, RefHandler, RefElement
from module.handle_query import QueryHandler

log = logging.getLogger(APP_NAME)
# Logging to console
slog = logging.getLogger(SLOGGER_NAME)
# Logging to files
flog = logging.getLogger(FLOGGER_NAME)

# MR number pattern matching all recognized reference formats
RE_MR = re.compile(
    r"(review\s*=\s*{\\MR\s*{\s*(?P<mrnumber1>[0-9]{5,10})(|\s+.*?)}\s*}(,|)"
    r"|(\\mr|\\mrnumber|\\bmrnumber|mrnumber|mr)(\s*=|)\s*"
    r"{(mr|)\s*(?P<mrnumber2>[0-9]{5,10})(|\s+.*?)\s*}(,|)"
    r"|({|)\s*MR(\s*|-|})(?P<mrnumber3>[0-9]{5,10})(|\s+.*?)\s*(},|}|,|.))",
    flags=re.IGNORECASE
    )

RE_BIBRE_LINE = re.compile(r'^%.*\r?\n$')
RE_BIBRE_PART = re.compile(r'\s*(.*?)(?<!\\)%.*\r?\n$')

RE_TEX_ACCENTS = re.compile(
    r"""(?:{|)\\(?:"|'|`|\^|-|H|~|c|k|=|b|\.|d|r|u|v|A)(?:|{)([a-zA-Z])}(?:}|)"""
)
RE_BRACED_LETTERS = re.compile(r"""(\s)(?<!\\)([a-zA-Z]*){([A-Z]+)}""")
RE_TEX_CS = re.compile(r'(\\bibinfo{[a-z]+}|\\[a-zA-Z]+)(\s|{)')

# Default bibstyle format
PLAIN = 'plain'

OUTPUT_ENV_FMT = {
    RefTypes.TEX: "\\begin{{thebibliography}}{{{}}}\n"
                  "\\csname bibmessage\\endcsname\n\n"
                  "{}"
                  "\\end{{thebibliography}}\n",
    RefTypes.AMSREFS: "\\begin{{bibdiv}}\n\\begin{{biblist}}\n\n"
                      "{}"
                      "\\end{{biblist}}\n\\end{{bibdiv}}",
    RefTypes.HTML: "<!DOCTYPE html>\n<html>\n<body>\n\n"
                   "{}"
                   "\n</body>\n</html>\n",
    Ext.AUX: "\\bibstyle{{{}}}\n"
             "{}"
             "\\bibdata{{{}}}"
}


class HandleBBL(object):
    """ This is the main class containing and initiating other classes'
        methods and attributes for provided input data processing.
    """

    query_items_limit = QUERY_ITEMS_LIMIT

    def __init__(self, inputfile, encoding, clean_comments,
                 itemno, wait, outputtype, bibstyle,
                 disable_queries=False, debug=0, version=str()):
        """ Initiate all methods and attributes required to process input data.

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
            disable_queries : bool (for testing purposes only)
                If queries should be omitted,
                all references will be processed up until query query to AMS DB
                should be performed and then it will be skipped
            bibstyle : str or None
                Used only if the requested output type is BIBTEX or IMS
            debug : int
                If debug value is greater than 0, debug messages will be
                written to the FileHandler.LOG file.  Also, depending on the
                given debug value, final data written to the input file will
                contain TeX comments with query data.
            version : str
        """

        self.stdt = StatisticsData()
        self.data_container = {suffix: "" for suffix in Ext.OUTPUT}
        self.refs_container = RefsContainer()

        self.fh = FilesHandler(encoding, inputfile, outputtype)
        self.rh = RefHandler(outputtype)
        self.qh = QueryHandler(outputtype, self.refs_container,
                               disable_queries)

        if itemno < QUERY_ITEMS_LIMIT:
            self.query_items_limit = itemno
        self.wait = wait

        self.outputtype = outputtype
        self.bibstyle = bibstyle
        flog.debug(f"Comments will be cleaned from the output: {clean_comments}")
        self.clean_comments = clean_comments
        self.debug = debug
        self.disable_queries = disable_queries
        self.version = version

        self.eof = False
        self.ifile_end_lines = list()

    @property
    def icontent(self):
        """ Returns input file content. """
        return self.fh.read(Ext.IN)

    def postprocess_ofiles(self, refcount):
        """ Depending on the requested bibliography output type,
            HandleBBL.data_container if filled with the required data
            for certain file types.

            Parameters
            ----------
            refcount: int
                If refcount is 0, it means no references have been found
                in the input file

            If requested bibliography output type is TEX,
            number of bibliography items found is written to the first line of
            FileHandler.data file.
        """

        if refcount == 0:
            return None

        # Preparing AUX file content, but will be written to *.aux file
        # only if required for selected output format
        aux_pattern = OUTPUT_ENV_FMT.get(Ext.AUX)
        self.data_container[Ext.AUX] = \
            aux_pattern.format(
                self.bibstyle,
                self.data_container[Ext.AUX],
                os.path.splitext(self.fh.get_fname(self.fh.data))[0]
                )

        # Formatting the DATA file output according to requested output format
        env_pattern = OUTPUT_ENV_FMT.get(self.outputtype, None)
        out_fmt_content = self.data_container.get(self.fh.data, "")
        if self.outputtype == RefTypes.TEX:
            # Total items count is known only after all references have been
            # processed, therefore '{thebibliography}' environment starting
            # string is written to container when all processing is finished
            self.data_container[self.fh.data] \
                = env_pattern.format(refcount, out_fmt_content)
        elif self.outputtype == RefTypes.AMSREFS:
            self.data_container[self.fh.data] \
                = env_pattern.format(out_fmt_content)
        elif self.outputtype == RefTypes.HTML:
            self.data_container[self.fh.data] \
                = env_pattern.format(out_fmt_content)

    def _remove_tex_comments(self, line):
        """ Remove TeX comments.

            Parameters
            ----------
            line : str

            Returns
            -------
            str
        """
        fmtline = RE_BIBRE_LINE.sub('', line)
        if fmtline:
            matchobj = RE_BIBRE_PART.search(fmtline)
            if matchobj is not None:
                return f"{matchobj.group(1)}\n"
            return fmtline
        return fmtline

    def _remove_tex_syntax(self, line):
        """ Remove TeX commands, accents and braces around upper case letters.

            BatchMRef may not found a reference in the AMS MR DB because of
            braces and accents present in reference string (tested), therefore
            accented letters "{\'a}" and "\'{a}" are changed to plain "a".
            "{ABC}" is changed to "ABC".
            LaTeX command sequences are changed to strings or deleted
            completely leaving their argument intact.

            Parameters
            ----------
            line : str

            Returns
            -------
            str
        """
        mline = RE_TEX_ACCENTS.sub(r'\1', line)
        if mline:
            mline = RE_BRACED_LETTERS.sub(r'\1\2\3', mline)
        tex_map = [
            [r'\ndash ', '-'],
            [r'\ndash', '-'],
            [r'\&', '&'],
            [r'\ ', ' ']
        ]
        for tex_input, replacement in tex_map:
            mline = mline.replace(tex_input, replacement)
        mline = RE_TEX_CS.sub(r'\2', mline)
        return mline

    def gather_records(self, require_env):
        """ Extract bibliography reference items from the input file.

            Parameters
            ----------
            require_env : bool
                If True, get bibliography reference items only inside
                the bibliography environment.  If False, gel all bibliography
                reference items found in the input file

            Yields
            -------
            str
                Denotes reference format type (one of RefTypes.ITYPES),
                bibliography environment state (RefTypes.BiblEnv.BEGIN or
                RefTypes.BiblEnv.END),
                or input file end mark (EOF)

            RefElement() instance, str, or None
                If reference of one of RefTypes.ITYPES type has been found,
                a RefElement() instance is returned with the following
                attributes filled in:
                reftype, citekey, biblabel,
                orig_lines, cleaned_lines, query_lines

                If end of input file has been determined, None is returned

                Otherwise current line is returned
        """

        def sort_comments_out(orig_lines, comment_lines):
            """ Assign gathered comment lines to the rightful reference item.

                Parameters
                ----------
                orig_lines: list
                comment_lines : list

                Returns
                -------
                list
                    Comment lines, belonging to current reference item
                list
                    Comment lines, belonging to the next reference item
            """
            next_elem_comment_lines = []
            next_elem_orig_lines = []
            reversed_orig_lines = orig_lines[::-1].copy()
            found = False
            skip = 0
            for no, line in enumerate(reversed_orig_lines.copy()):
                if not found and not line.strip():
                    skip = no+1
                    continue
                elif line.strip() and line in comment_lines:
                    found = True
                    next_elem_comment_lines.append(comment_lines.pop(-1))
                    for _ in range(0, skip, 1):
                        next_elem_orig_lines.append(orig_lines.pop(-1))
                    skip = 0
                    next_elem_orig_lines.append(orig_lines.pop(-1))
                else:
                    break
            return orig_lines, comment_lines, \
                next_elem_orig_lines[::-1], next_elem_comment_lines[::-1]

        # Allowing gathering the references according to
        # the bibliography environment status
        envmap = {RefTypes.BiblEnv.BEGIN: True,
                  RefTypes.BiblEnv.END: False,
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
            additional_info = {}
            if search:
                reftype, additional_info = self.rh.find_reference(clean_line)

            if require_env and reftype == RefTypes.BiblEnv.ENV:
                if element.reftype is not None:
                    # Full bibliography item
                    element.orig_lines, element.comment_lines, \
                        next_elem_orig_lines, next_elem_comment_lines = \
                        sort_comments_out(element.orig_lines, element.comment_lines)
                    yield element.reftype, element
                    element = RefElement()
                    element.orig_lines = next_elem_orig_lines
                    element.comment_lines = next_elem_comment_lines

                # Bibliography environment
                envstatus = additional_info.pop("envstatus", None)
                if envstatus in envmap:
                    gather = envmap[envstatus]
                    search = gather
                    yield envstatus, line
                    continue

            elif reftype in RefTypes.ITYPES:
                multiline = additional_info.get("line", "")
                if multiline:
                    continue

                if element.reftype is not None:
                    # Full bibliography item
                    element.orig_lines, element.comment_lines, \
                        next_elem_orig_lines, next_elem_comment_lines = \
                        sort_comments_out(element.orig_lines, element.comment_lines)
                    yield element.reftype, element
                    element = RefElement()
                    element.orig_lines = next_elem_orig_lines
                    element.comment_lines = next_elem_comment_lines

                if gather:
                    element.reftype = reftype
                    element.citekey = additional_info.get("citekey", None)
                    element.biblabel = additional_info.get("biblabel", None)
                    element.orig_lines.append(line)
                    if RE_MR.search(clean_line
                                    .replace(str(element.citekey), "")
                                    .replace(str(element.biblabel), "")) \
                            is not None:
                        element.orig_mrid = True
                    element.cleaned_lines.append(clean_line)

                    ref_format_free_line = additional_info.get("text", clean_line)
                    if RE_MR.search(ref_format_free_line
                                    .replace(str(element.citekey), "")
                                    .replace(str(element.biblabel), "")) \
                            is not None:
                        element.orig_mrid = True
                    accent_free_line = self._remove_tex_syntax(ref_format_free_line)
                    element.query_lines.append(accent_free_line)
                    continue

            if gather and element.reftype is not None:
                element.orig_lines.append(line)
                if RE_MR.search(clean_line
                                .replace(str(element.citekey), "")
                                .replace(str(element.biblabel), "")) \
                        is not None:
                    element.orig_mrid = True
                element.cleaned_lines.append(clean_line)
                accent_free_line = self._remove_tex_syntax(clean_line)
                element.query_lines.append(accent_free_line)
            else:
                # Before and after the bibliography environment
                outside_lines = line
                if envstatus == RefTypes.BiblEnv.ENV:
                    outside_lines += "".join(element.orig_lines)
                    element = RefElement()
                yield envstatus, outside_lines

        final_orig_lines = []
        if element.reftype is not None:
            # The last full bibliography item
            element.orig_lines, element.comment_lines, final_orig_lines, _ = \
                sort_comments_out(element.orig_lines, element.comment_lines)
            yield element.reftype, element

        yield EOF, "".join(final_orig_lines)

    def transfer_to_file(self):
        """ After each query to BatchMRef write gathered data into files.
            Fills StatisticsData attributes values according
            to processed reference final status.
        """
        for elem in self.refs_container.elems:
            if self.refs_container.qerrno != 0:
                elem.errno = self.refs_container.qerrno
            outstring = ''.join(elem.cleaned_lines if self.clean_comments else
                                elem.orig_lines)

            elem.outref = self.rh.insert_citekey(
                elem.outref, elem.citekey, elem.biblabel,
                elem.normalize(elem.cleaned_lines[1:]))
            if elem.mrid is not None:
                outstring = self.rh.insert_mrid(elem.reftype, outstring, elem.mrid)
                slog.info(elem.mrid)
                msg = f'Found: {{{elem.citekey}}} -> MR{elem.mrid}'
            elif elem.errno == -1:
                self.stdt.NOT_FOUND += 1
                msg = f'NotFound: {{{elem.citekey}}}'
                slog.warning(msg)
            elif elem.orig_mrid:
                self.stdt.SKIP += 1
                msg = f'Skipping: {{{elem.citekey}}} -> MR already present'
                slog.warning(msg)
            elif self.disable_queries:
                self.stdt.SKIP += 1
                msg = f'Skipping: {{{elem.citekey}}} ' \
                      f'-> option --disable_queries used'
                slog.info(msg)
            else:
                self.stdt.ERROR += 1
                msg = f'QueryError: {{{elem.citekey}}} -> see *.{Ext.ERR} file'
                flog.error(msg)
                slog.error(msg)
            flog.info(msg)

            if self.clean_comments and self.debug > 0:
                outstring = "".join(elem.comment_lines) + outstring

            if self.debug == 1:
                outstring = f'%% {elem.querystring}\n{outstring}'
            elif self.debug == 2:
                outstring = f'%% {elem.errno}\n{outstring}'
            elif self.debug == 3:
                outstring = f'%% {elem.querystring}\n' \
                            f'%% {elem.errno}\n{outstring}'

            flog.debug(f"\n{'>' * 70}"
                       f"\nFINAL reference with MR id in original format:"
                       f"\n\n{outstring.strip()}\n")

            if elem.outref is not None:
                flog.debug(f"FINAL reference in '{self.outputtype}' format:"
                           f"\n\n{elem.outref.strip()}\n{'<' * 70}")
            self.data_container[Ext.OUT] += outstring
            self.data_container[self.fh.data] += elem.outref if elem.outref else ""
            self.data_container[Ext.AUX] += f'\\citation{{{elem.citekey}}}\n'

            if elem.errno == 0 and self.refs_container.qerrno == 0 \
                    and not elem.orig_mrid:
                self.stdt.SUCCESS += 1

        if self.eof:
            while self.ifile_end_lines:
                self.data_container[Ext.OUT] += self.ifile_end_lines.pop(0)

        self.refs_container = RefsContainer()
        self.qh._refs_container = self.refs_container

    def get_mr_codes(self, require_env):
        """ Analyze input file content and process found reference items.

            Parameters
            ----------
            require_env : bool
                If True, and if no bibliography reference items have been found
                inside the bibliography environment, or an environment hasn't
                been found at all, parameter is set to False in this method and
                reruns itself in order to search reference items in
                the whole input file.

            If reference item of RefTypes.ITYPES has been found, current
            RefElement() instance attribute 'refid' is assigned a value
        """

        msg = "in the bibliography environment only" \
            if require_env else "in the whole input file"
        flog.debug(f"SEARCHING for reference items: {msg}")

        valid = 0
        records = self.gather_records(require_env=require_env)
        pseudo_citekey = 0
        for reftype, record in records:
            if reftype == EOF:
                self.eof = True
                self.ifile_end_lines.append(record)

            elif reftype not in RefTypes.ITYPES:
                if reftype != RefTypes.BiblEnv.END:
                    self.data_container[Ext.OUT] += record
                else:
                    self.ifile_end_lines.append(record)

            elif valid == 0 or valid % self.query_items_limit != 0:
                self.stdt.TOTAL += 1

                record.refid = self.stdt.TOTAL
                if not record.citekey:
                    pseudo_citekey += 1
                    record.citekey = pseudo_citekey

                flog.debug("=" * 70)
                flog.debug(f"FOUND reference {self.stdt.TOTAL}: "
                           f"type={reftype}, "
                           f"cite_key={record.citekey}, "
                           f"biblabel={record.biblabel}, "
                           f"orig_mrid={record.orig_mrid}")

                if reftype != RefTypes.BIBITEM:
                    record.querystring = \
                        self.rh.extract_keys_data(record.query_lines)
                self.refs_container.append_elem(record)
                if not record.orig_mrid:
                    # for the record query is performed
                    # only if it does not contain MR ID originally
                    record.errno = self.qh.prepare_query_str(record.refid,
                                                             record.querystring,
                                                             self.fh.encoding)
                    if record.errno == 0:
                        valid += 1

            if valid != 0 and (valid % self.query_items_limit == 0
                               or self.eof):
                self.qh.query()
                self.transfer_to_file()
                valid = 0
                if not self.eof:
                    time.sleep(self.wait)

        if self.stdt.TOTAL == 0 and require_env:
            # If no bibliography items were found in the bibliography
            # environment, then trying to search for them everywhere
            # in the input file
            flog.debug("FOUND no references! Changing the search mode ... ")
            self.eof = False
            self.ifile_end_lines = list()
            self.data_container[Ext.OUT] = ""
            return self.get_mr_codes(require_env=False)

        self.transfer_to_file()

        flog.debug("=" * 70)

    def run(self, require_env):
        """ Main method. Analyzes provided input file
            and creates required output files.

            Parameters
            ----------
            require_env : bool
        """

        slog.info(f"# {self.version} #\nJob started")
        beg = time.time()

        self.get_mr_codes(require_env=require_env)
        self.postprocess_ofiles(refcount=self.stdt.TOTAL)

        duration = int(round(time.time() - beg))

        msg = f"Total: {self.stdt.TOTAL}, " \
              f"found: {self.stdt.SUCCESS}, " \
              f"not found: {self.stdt.NOT_FOUND}, " \
              f"query errors: {self.stdt.ERROR}, " \
              f"skipped: {self.stdt.SKIP}"
        fmsg = f"   {msg.lower()}, time: {duration}s"
        flog.info(fmsg)
        if self.stdt.ERROR:
            flog.error(fmsg)

        slog.info("Job ended")
        slog.info(msg)
        slog.info(f'Job completed in {duration}s')

        fmt_files = RefTypes.OTYPES.get(self.outputtype, [Ext.DATA])
        for suffix, content in self.data_container.items():
            if (suffix in fmt_files or suffix == Ext.OUT) and content:
                with open(self.fh.get_fname(suffix), FileMask.WRITE,
                          encoding=self.fh.encoding) as out:
                    out.write(content)

        self.fh.finalize_files()
