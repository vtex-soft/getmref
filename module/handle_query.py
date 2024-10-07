import functools
import logging
import re
import requests
import urllib  # used only if --debug > 0
from xml.dom.minidom import parseString
from xml.parsers.expat import ExpatError

from module.constants import \
    Enc, RefTypes, AMS_URL, AMS_MSG, APP_NAME, SLOGGER_NAME, FLOGGER_NAME

log = logging.getLogger(APP_NAME)
# Logging to console
slog = logging.getLogger(SLOGGER_NAME)
# Logging to files
flog = logging.getLogger(FLOGGER_NAME)

QUERY_XML_HEADING_STRING = '<?xml version="1.0" encoding="UTF-8"?>\n'

QUERY_HEADING_PATTERN = [
    '<mref_batch>',
    ' {}',
    '</mref_batch>'
]

QUERY_ITEM_PATTERN = [
    '<mref_item outtype="{}">',
    ' <inref>',
    '  {}',
    ' </inref>',
    ' <myid>{}</myid>',
    '</mref_item>\n',
]

HMTL_ENTITIES_MAP = [
    ("<", '&lt;'),
    (">", '&gt;'),
    ("&", '&amp;')
]

QUERY_FORMATS = {
    RefTypes.TEX: RefTypes.TEX,
    RefTypes.BIBTEX: RefTypes.BIBTEX,
    RefTypes.IMS: RefTypes.BIBTEX,
    RefTypes.AMSREFS: RefTypes.AMSREFS,
    RefTypes.HTML: RefTypes.HTML,
    None: RefTypes.TEX
}

RE_MREF_ITEM = re.compile(
    '(<mref_item outtype="(?:bibtex|tex|amsrefs|html)">.*?</mref_item>)',
    re.DOTALL
)
RE_BATCH_ERROR = re.compile('<batch_error>(.*?)</batch_error>', re.DOTALL)


class HTMLExitCodes:
    OK = 200
    FAILED = 412


class QueryHandler(object):
    """ This class unites methods and attributes related to actions necessary
        for the AMS BatchMRef query """

    def __init__(self, outputtype, refs_container,
                 disable_queries=False, address=AMS_URL):
        """ Initiate query to BatchMRef handling methods and attributes

            Parameters
            ----------
            outputtype : str or None
                Reference output format type passed for BatchMRef query
            refs_container : RefsContainer() instance
            disable_queries : bool (for testing purposes only)
                If queries should be omitted,
                all references will be processed up until query to AMS DB should
                be performed and then it will be skipped
            address : str
                BatchMRef query address
        """

        self.address = address
        self.query_format = QUERY_FORMATS.get(outputtype, RefTypes.TEX)
        flog.debug(f"Query settings: URL = {address}, "
                   f"output format = {self.query_format}")
        self.outputtype = outputtype

        self.errno = 0
        self.qresult = None
        self.qcode = None
        self.xml = None
        self.disable_queries = disable_queries

        self._refs_container = refs_container
        self.query_elems = list()

    @property
    def refs_container(self):
        """ Container for all obtained and analyzed references.

            Returns
            -------
            RefsContainer() instance
        """
        return self._refs_container

    def _encode_str(self, istring, encoding=Enc.ASCII):
        """ Change query string encoding into the ASCII.
            Required for correct input processing on AMS side.

            Parameters
            ----------
            istring : str
            encoding : str
                Input file encoding

            Returns
            -------
            str
        """
        if encoding == Enc.ASCII:
            return istring

        try:
            return istring.encode(Enc.ASCII, errors='replace').decode()
        except:
            msg = ">> encoding given reference element FAILED!"
            flog.debug(msg)
            flog.exception(f"{msg}\n[Input string]:\n{istring}\n")
            self.errno = -2
            return istring

    @staticmethod
    def _escape_xml_entities(istring):
        """ Convert HTML entities into XML valid symbols.

            Parameters
            ----------
            istring : str

            Returns
            -------
            str
        """

        flog.debug(">> Converting TeX symbols into XML valid symbols")
        return functools.reduce(
            lambda string, transl: string.replace(transl[0], transl[1]),
            (istring, *HMTL_ENTITIES_MAP)
            )

    def _parse_str(self, istring, check=False):
        """ Parse string into XML object.

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
            msg = ">> Parsing given XML FAILED!"
            flog.debug(msg)
            flog.exception(f"{msg}\n[Parse query]:\n{istring}\n")
            self.errno = err.code

    def prepare_query_str(self, refid, querystring, encoding):
        """ Format the reference as an XML string and validate it.

            Parameters
            ----------
            refid : int
                RefElement() instance id
            querystring : str
            encoding: str
                Input file encoding

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
            "\n".join(QUERY_ITEM_PATTERN).format(
                self.query_format,
                self._escape_xml_entities(querystring),
                refid
                ),
            encoding
            )
        flog.debug(f">> Formed query XML:"
                   f"\n{'~' * 70}\n{single_qstring}\n{'~' * 70}")

        # Checking if formed string is a valid XML
        self._parse_str(single_qstring, check=True)
        if self.errno != 0:
            return self.errno

        self.query_elems.append(single_qstring)
        return self.errno

    def _send_query(self, querystring, do_not_send=False):
        """ Send query to BatchMRef

            Parameters
            ----------
            querystring : str
                Validated XML query string, containing as many reference items
                as QUERY_ITEMS_LIMIT allows
            do_not_send : bool (for testing purposes only)
                If queries should be omitted, skipping the request to AMD DB.

            If request to BatchMRef was successful, saving query result,
            otherwise qcode will provide what kind of error was returned.
        """
        self.qcode = None
        self.qresult = None

        flog.debug("SENDING query ...")

        queryinfo = {'qdata': querystring}
        headers = {'user-agent': APP_NAME}
        flog.debug(f">> Query POST headers: {headers}")
        flog.debug(f">> Query POST raw data: {queryinfo}")
        flog.debug(f">> Query POST encoded data: "
                   f"{urllib.parse.urlencode(queryinfo)}")

        if do_not_send:
            log.debug(">> Query SKIPPED!")
            return

        try:
            req = requests.post(url=self.address, data=queryinfo, headers=headers)
        except:
            msg = ">> Query FAILED!"
            flog.exception(msg)
            self.qcode = HTMLExitCodes.FAILED
        else:
            self.qcode = req.status_code
            flog.debug(f">> Query result code: {self.qcode}")
            self.qresult = req.text

            if self.qcode == HTMLExitCodes.OK and \
                    self.qresult.startswith(QUERY_XML_HEADING_STRING):
                msg = f">> Query result string:" \
                      f"\n{'~'*70}\n{self.qresult.strip()}\n{'~'*70}"
            else:
                msg = AMS_MSG if AMS_MSG in self.qresult else ""
                flog.error(f"Query returned an error:\n\n{msg}\n\n{self.qresult}")
                msg = f">> Query FAILED! \n{msg}"
                self.qcode = self.qcode if self.qcode != HTMLExitCodes.OK \
                    else HTMLExitCodes.FAILED
                self.qresult = None
        flog.debug(msg)

    @staticmethod
    def _extract_xml_data(xml_elem, tag):
        """ Extract text data from an XML object.

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
            parsed into XML object.

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
        elem = self.refs_container.get_elem_by_refid(refid)

        matches = self._extract_xml_data(mref_item, "matches")
        if matches == '1':
            flog.debug(f">> MRef DB: reference `{elem.citekey}' found!")
            elem.mrid = self._extract_xml_data(mref_item, "mrid")
            flog.debug(f">> MRef ID: {elem.mrid}")

            if self.outputtype is not None:
                elem.outref = self._extract_xml_data(mref_item, "outref")
                flog.debug(f">> MRef output reference:"
                           f"\n{'~'*70}\n{elem.outref.strip()}\n{'~'*70}")
        else:
            elem.errno = -1
            flog.debug(f">> MRef DB: reference `{elem.citekey}' not found!")

    def query(self):
        """ Send a request to AMS BatchMRef and analyze the returned data.

            If query result contains 'batch_error' element or returned
            XML string can't be parsed into XML object,
            RefsContainer() instance gets a non-zero error code.
        """

        querystring = QUERY_XML_HEADING_STRING \
                      + "\n".join(QUERY_HEADING_PATTERN) \
                            .format("\n".join(self.query_elems).strip())
        self._send_query(querystring, do_not_send=self.disable_queries)
        self.errno = 0 if self.qcode in [HTMLExitCodes.OK, None] else self.qcode
        if self.errno == 0 and self.qresult is not None:
            error_obj = RE_BATCH_ERROR.search(self.qresult)
            if error_obj:
                flog.debug(">> Query XML contains an ERROR!")
                flog.error(f"[batch_error]:"
                           f"\n{error_obj.group(1)}"
                           f"\n\n[querystring]:\n{querystring}")
                self.errno = -2
            flog.debug("Splitting query result and "
                       "analyzing parts separately")
            for item_qresult in RE_MREF_ITEM.finditer(self.qresult):
                self.xml = None
                self._parse_str(item_qresult.group())
                if self.xml is not None:
                    self._analyze_xml(self.xml)

        if self.errno != 0 or self.qcode is not None:
            # updating status if query has been sent
            # and/or some problems detected
            self.refs_container.qerrno = self.errno
        self.query_elems = list()
