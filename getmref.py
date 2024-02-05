#! /usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
getmref.py - gets the references links to MathSciNet through the BatchMRef:
             https://mathscinet.ams.org/batchmref?qdata=xmldocument

Copyright (C) 2023 Sigitas Tolušis, VTeX Ltd., Jim Pitman, Dept. Statistics,
U.C. Berkeley and Lolita Tolenė, VTeX Ltd.
E-mail: latex-support@vtex.lt
http://www.stat.berkeley.edu/users/pitman

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

Requires:
- python ver. >=3.9
- [ for option --enc=auto ]
  Universal Encoding Detector library, written by Mark Pilgrim.

Usage:
  getmref.py <bbl or tex file>

Program (description):
- makes inputfile copy to <inputfilename>.getmref.bak;
- for each successful bibitem reference search adds line \MR{<mrid>},
  where <mrid> is data from XML tag <mrid> without front symbols "MR";
- writes all adds to <inputfilename>;
- generates log file <inputfilename>.getmref.log;
- writes to stdout log info

Changes:
2004/04/26 - \bibitem line removed from the query
2017/01/12 - input file may contain 'amsrefs', 'bibtex' and 'tex' type
             references (all at once);
             input references can be formatted as 'amsrefs', 'bibtex',
             'tex' or 'html' type references
"""

import os
import logging
import argparse

from module.constants import Enc, Ext, RefTypes, APP_NAME
from module.handle_logging import setup_logging_files
from module.handle_bbl import PLAIN, HandleBBL

__author__ = "Sigitas Tolušis, Jim Pitman, Lolita Tolenė"
__title__ = APP_NAME
__version__ = "3.2.1"
__email__ = "lolita.tolene@vtex.lt"
__status__ = "Production"

log = logging.getLogger(APP_NAME)
log.addHandler(logging.NullHandler())
flog = slog = log

VERSION = f"{__title__}, v{__version__}"
DESCRIPTION = (
        f"Tool {VERSION}, is designed for: " 
        "(1) getting MR numbers for given references from AMS MRef database, "
        "(2) formatting the given references in one of AMS allowed formats. "
        f"Maintainer: L. Tolene {__email__}."
    )


def get_cmd_args():
    """ Command line input parser. """

    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("filepath", help="References containing file")
    parser.add_argument(
        "--enc", '-e', type=str, default=Enc.LATIN1,
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
        "--bibstyle", '-s', default=PLAIN,
        help="BibTeX style. For more information please consult "
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
        help="Time (in seconds) to wait between queries to AMS batchmref."
    )
    parser.add_argument(
        "--disable_queries", action='store_true',
        help="For testing purposes only. No queries to DB will be sent. "
             "Useful because they can return unstable results.")
    parser.add_argument(
        "--debug", '-d', choices={0, 1, 2, 3}, default=0, type=int,
        help="Outputs additional info for debugging purposes."
             "0 - *.log file contains only essential info;"
             "1-3 - *.log file contains all debug info, "
             "the input file will be supplemented with query related info: "
             "1 - query string, 2 - query status, 3 - 1+2."
    )
    parser.add_argument(
        "--version", '-v', action='version', version=VERSION,
        help="Module version."
    )
    return parser.parse_args()


if __name__ == '__main__':
    import sys
    from module.constants import SLOGGER_NAME, FLOGGER_NAME

    # Logging to console
    slog = logging.getLogger(SLOGGER_NAME)
    # Logging to files
    flog = logging.getLogger(FLOGGER_NAME)

    # Get input parameter values
    args = get_cmd_args()
    # Setup logging files
    setup_logging_files(debug=args.debug if not args.disable_queries else 1,
                        basename=os.path.splitext(args.filepath)[0])
    # Create HandleBBL() instance
    bblobj = HandleBBL(inputfile=args.filepath, encoding=args.enc,
                       clean_comments=args.clean,
                       itemno=args.itemno, wait=args.wait,
                       outputtype=args.format, bibstyle=args.bibstyle,
                       disable_queries=args.disable_queries,
                       debug=args.debug, version=VERSION)
    # Process input file
    try:
        bblobj.run(require_env=not args.nobibenv)
    except BaseException as error:
        flog.error(f"Program failed:\n{str(error)}")
        flog.info(f"Program failed! See *.{APP_NAME.lower()}.{Ext.ERR} file")
        sys.exit(1)
