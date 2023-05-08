APP_NAME = "GetMRef"
SLOGGER_NAME = f"{APP_NAME}.StreamLogger"
FLOGGER_NAME = f"{APP_NAME}.FileLogger"


class Enc:
    AUTO = "auto"
    LATIN1 = "latin1"
    ASCII = "ascii"
    UTF8 = "utf-8"


class Ext:
    IN = 'in'
    BAK = 'bak'
    OUT = 'out'
    AUX = 'aux'
    DATA = 'data'
    BIB = 'bib'
    HTML = 'html'

    LOG = 'log'
    ERR = 'err'

    GMR = 'getmref'

    OUTPUT = (OUT, DATA, BIB, AUX, HTML)


class RefTypes(object):
    r""" This class declares recognized bibliography reference formats.

        Formats description
        -------------------
        Source: only AMS
        "tex": LaTeX code without any specific beginning/ending;
               MR number is given in plain text
        "html": <a href="https://mathscinet.ams.org/mathscinet-getitem?mr=<7digits>">
                    <7digits>
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

    # Declaration of reference input formats
    # and their typical ending and MR id format
    class BibtexFmt:
        REF_ENDING = "}"
        MR_FORMAT = ",\nMRNUMBER={{{}}},\n"

    class AmsrefsFmt:
        REF_ENDING = "}"
        MR_FORMAT = ",\nreview={{\\MR{{{}}}}},\n"

    class BibitemFmt:
        REF_ENDING = "\\endbibitem"
        MR_FORMAT = "\n\\MR{{{}}}\n"

    ITYPES = {
        BIBTEX: BibtexFmt,
        AMSREFS: AmsrefsFmt,
        BIBITEM: BibitemFmt
    }

    # Declaration of reference output formats
    # and output file types required for each type
    OTYPES = {
        BIBTEX: [Ext.BIB, Ext.AUX],
        IMS: [Ext.BIB, Ext.AUX],
        HTML: [Ext.HTML],
        TEX: [Ext.DATA],
        AMSREFS: [Ext.DATA]
    }

    class BiblEnv:
        """ This class provides some constants referring to
            bibliography environment used for the input file content analysis.
        """
        ENV = "environment"
        BEGIN = "begin"
        END = "end"


# >>> AMS MATHSCINET >>>
AMS_URL = 'https://mathscinet.ams.org/batchmref'
# AMS gives the following message in HTML if requested website is broken
AMS_MSG = "The AMS Website is temporarily unavailable."
# AMS BatchMRef limit of items no per query
QUERY_ITEMS_LIMIT = 100
# <<< AMS MATHSCINET <<<
