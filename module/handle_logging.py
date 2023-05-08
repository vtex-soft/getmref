import sys
import logging
from module.constants import Ext, Enc, APP_NAME, SLOGGER_NAME, FLOGGER_NAME

BASICFORMATTER = logging.Formatter('%(message)s')
DEBUGFORMATTER = logging.Formatter('%(levelname)s %(message)s')


class LessThanFilter(logging.Filter):
    """ This class allows to add an upper bound to the logged messages.

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


log = logging.getLogger(APP_NAME)
# Logging to console
slog = logging.getLogger(SLOGGER_NAME)
# Logging to files
flog = logging.getLogger(FLOGGER_NAME)


def setup_logging_files(debug, basename):
    """ Setup logging files.

        Parameters
        ----------
        debug : int
        basename: str
            Input file name
    """

    if debug == 0:
        log_min_level = logging.INFO
        log_max_level = logging.INFO
        formatter = BASICFORMATTER
    else:
        log_min_level = logging.DEBUG
        log_max_level = logging.WARN
        formatter = DEBUGFORMATTER

    # Logging to console
    osh = logging.StreamHandler(stream=sys.stdout)
    osh.setFormatter(BASICFORMATTER)
    osh.setLevel(logging.INFO)
    osh.addFilter(LessThanFilter(logging.INFO))

    esh = logging.StreamHandler(stream=sys.stderr)
    esh.setFormatter(BASICFORMATTER)
    esh.setLevel(logging.WARN)
    slog.addHandler(osh)
    slog.addHandler(esh)
    slog.setLevel(logging.INFO)

    # Logging to files (they will be overwritten each time the program starts)
    # LOG file will be created only if there are request
    # to write messages into it
    ofh = logging.FileHandler(filename=f"{basename}.{Ext.GMR}.{Ext.LOG}",
                              mode='w', delay=True, encoding=Enc.UTF8)
    ofh.setFormatter(formatter)
    ofh.setLevel(log_min_level)
    ofh.addFilter(LessThanFilter(log_max_level))
    flog.addHandler(ofh)

    # ERR file has to be always present
    efh = logging.FileHandler(filename=f"{basename}.{Ext.GMR}.{Ext.ERR}",
                              mode='w', delay=False, encoding=Enc.UTF8)
    efh.setFormatter(DEBUGFORMATTER)
    efh.setLevel(logging.ERROR)
    flog.addHandler(efh)

    flog.setLevel(logging.DEBUG)


class StatisticsData(object):
    """ This class declares containers for statistical data.
    """
    # Total bibliography reference items found
    TOTAL = 0
    # Number of references for which data has been successfully obtained
    SUCCESS = 0
    # Number of references for which data has been not found
    NOT_FOUND = 0
    # Total number of skipped references
    # (only because MR code was already provided
    #  or queries to AMS DB are disabled by user)
    SKIP = 0
    # Number of reference items processed with errors count
    ERROR = 0
