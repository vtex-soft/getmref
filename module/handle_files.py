import chardet
import os
import shutil
import logging

from module.constants import \
    Enc, Ext, RefTypes, APP_NAME, SLOGGER_NAME, FLOGGER_NAME

log = logging.getLogger(APP_NAME)
# Logging to console
slog = logging.getLogger(SLOGGER_NAME)
# Logging to files
flog = logging.getLogger(FLOGGER_NAME)


class FileMask:
    READ_BINARY = 'rb'
    READ = 'r'
    WRITE = 'w'


# Mark of the input file ending
EOF = "EOF"


class FilesHandler(object):
    """ This class unites methods and attributes related to
        files I/O actions. """

    def __init__(self, encoding, infile, outputtype):
        """ Initiate file handling methods and attributes.

            Parameters
            ----------
            encoding: str or None
                Encoding to read infile
            infile : str or None
                Path to input file
            outputtype : str or None
                Required bibliography reference output format type
        """

        self.encoding = encoding
        self.infile = infile
        self._basename = os.path.splitext(infile)[0]

        # Determining needed file types for given reference output type
        msg = f"The given references will be formatted in " \
              f"'{outputtype if outputtype is not None else 'orig'}' format. "

        fmt_files = RefTypes.OTYPES.get(outputtype, [Ext.DATA])
        # Main output file is set according to requested output format
        self.data = fmt_files[0]
        msg += f"Additional files will be created: " \
               f"{', '.join([f'*.{sfx}' for sfx in fmt_files])}"

        self.files = dict()
        for suffix in Ext.OUTPUT:
            # Deleting old files
            self.delete(suffix)
            if suffix not in fmt_files:
                continue
            self.set_fname(suffix)

        flog.info(f"File: {infile}")
        if not (os.path.isfile(infile) and os.path.exists(infile)):
            logging.shutdown()
            raise ValueError(f"Provided source file '{infile}' does not exist! "
                             f"Please provide the valid one.")

        flog.debug(f"Workdir: {os.path.abspath(os.path.dirname(infile))}")
        flog.debug(msg)
        flog.debug(f"Provided encoding format: {self.encoding}")

    def set_fname(self, suffix):
        """ Set a filepath for a file with the provided suffix.

            Parameters
            ----------
            suffix : str
                File suffix without punctuation
        """
        filepath = f"{self._basename}.{Ext.GMR}.{suffix}" \
            if suffix != Ext.IN else self.infile
        self.files.update({suffix: filepath})

    def get_fname(self, suffix):
        """ Get filepath of a file with the required suffix.

            Parameters
            ----------
            suffix : str
                File suffix without punctuation

            Returns
            -------
            str
                The filepath
        """
        return self.files.get(suffix, self.set_fname(suffix))

    def _guess_encoding(self, suffix):
        """ Uses Universal Encoding Detector library in order
            to guess the encoding for provided file.

            Parameters
            ----------
            suffix : str
                File suffix without punctuation

            Returns
            -------
            str or None
                The encoding if guess was successful, None otherwise
        """
        flog.debug(f">> Trying to guess encoding...")
        rawdata = open(self.get_fname(suffix), FileMask.READ_BINARY).read()
        result = chardet.detect(rawdata)
        str_enc = result.get('encoding', Enc.ASCII)
        flog.debug(f">> Determined string encoding: {str_enc}")
        if str_enc is None:
            flog.debug(f">> Encoding determination has FAILED! "
                       f"Switching to '{Enc.ASCII}' encoding")
            str_enc = Enc.ASCII
        return str_enc

    def read(self, suffix=Ext.IN):
        """ Get the content of a file with the required suffix.
            Also sets the global encoding attribute if it was not set by user.

            Parameters
            ----------
            suffix : str
                File suffix without punctuation

            Yields
            ------
            str
        """
        if self.encoding in [Enc.AUTO, None]:
            # TODO: If this method would be used not only for the input file
            #  reading, encoding value should remain local
            self.encoding = self._guess_encoding(suffix)
        try:
            with open(self.get_fname(suffix),
                      FileMask.READ, encoding=self.encoding) as ifile:
                for iline in ifile:
                    yield iline
        except Exception as error:
            raise ValueError(f"Error while reading input file: {str(error)}. "
                             f"Please try using different encoding")

    def delete(self, suffix):
        """ Delete the file with the required suffix.

            Parameters
            ----------
            suffix : str
                File suffix without punctuation
        """
        dfile = self.get_fname(suffix)
        try:
            os.unlink(dfile)
            flog.debug(f"Deleted: {os.path.split(dfile)[1]}")
        except OSError:
            if os.path.isfile(dfile) and os.path.exists(dfile):
                flog.exception(f"Can't remove file: {dfile}")

    def finalize_files(self):
        """ Close all logging instances, create backup of the input file and
            overwrite it with the new content, delete temporary files.
        """
        flog.debug("Finalizing files...")

        bfile = self.get_fname(Ext.BAK)
        if not os.path.exists(bfile):
            os.rename(self.infile, bfile)
            flog.debug(f"Created backup of the input file: "
                       f"{os.path.split(bfile)[1]}")

        ofile = self.get_fname(Ext.OUT)
        if os.path.exists(ofile):
            shutil.copy2(ofile, self.infile)
            flog.debug(f"The input file is overwritten with: "
                       f"{os.path.split(ofile)[1]}")
            self.delete(Ext.OUT)
        else:
            flog.debug("The original file wasn't modified.")

        logging.shutdown()
