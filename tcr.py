# -*- encoding:utf-8 -*-
# !/usr/bin/env python
#
# reference google rietveld(include soso's modify) upload.py
#
"""
Tool for uploading diffs from subversion to TCR(Tencent CodeReview).
Usage summary: upload.py [options] [-- diff_options] [path...]
Diff options are passed to the diff command of the underlying system.
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
import django
# from django.conf import settings
# from autosystem import settings as default_settings

# settings.configure(default_settings=default_settings)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'autosystem.settings')
django.setup()

import codecs
import configparser
import fnmatch
import json
import mimetypes
import optparse
import os
import re
import subprocess
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse, urlunparse, urlencode
import hashlib
import logging
from typing import List
from Lockapi.models import TCR

try:
    import readline
except ImportError:
    pass
try:
    # import keyring
    keyring = None
except ImportError:
    keyring = None
# The logging verbosity:
#  0: Errors only.
#  1: Status messages.
#  2: Info logs.
#  3: Debug logs.
verbosity = 1
# URL of the default review server. This line could be
# changed by the review server (see handler for tcr.py).
DEFAULT_REVIEW_SERVER = "code.woa.com"
DEFAULT_NEEDED_PARAMETERS = ('isclient', 'true')
ENCODING_ALL = ('ascii', 'gbk', 'utf-8')
VERSION = 25
REAL_VERSION = "2." + str(VERSION)
REAL_VERSION_ANOTHER = "2_" + str(VERSION)
# Max size of patch or base file.
MAX_UPLOAD_SIZE = 5 * 1024 * 1024
# Constants for version control names.  Used by GuessVCSName.
VCS_GIT = "Git"
VCS_MERCURIAL = "Mercurial"
VCS_SUBVERSION = "Subversion"
VCS_UNKNOWN = "Unknown"
IGNORE_FILE_SUFFIX = ['jar', 'class', 'svn', 'dll', 'bmp', 'jpeg', 'jpg', 'png', 'gif', 'pic', 'tif', 'iso', 'rar',
                      'zip', 'exe', 'pdf', 'rm',
                      'avi', 'wav', 'aif', 'au', 'mp3', 'ram', 'mpg', 'mov', 'swf', 'xls', 'xlsx', 'doc', 'docx', 'mid',
                      'ppt', 'pptx', 'mmap',
                      'msi', 'lib', 'ilk', 'obj', 'aps', 'def', 'dep', 'pdb', 'tlb', 'res', 'manifest', 'hlp', 'wps',
                      'arj', 'gz',
                      'z', 'adt', 'com', 'a', 'bin', '3ds', 'drw', 'dxf', 'eps', 'psd', 'wmf', 'pcd', 'pcx', 'psp',
                      'rle', 'raw', 'sct', 'tga',
                      'tiff', 'u3d', 'xbm', 'bytes']
# whitelist for non-binary filetypes which do not start with "text/"
# .mm (Objective-C) shows up as application/x-freemind on my Linux box.
TEXT_MIMETYPES = ['application/javascript', 'application/x-javascript',
                  'application/xml', 'application/x-freemind']
VCS_ABBREVIATIONS = {
    VCS_MERCURIAL.lower(): VCS_MERCURIAL,
    "hg": VCS_MERCURIAL,
    VCS_SUBVERSION.lower(): VCS_SUBVERSION,
    "svn": VCS_SUBVERSION,
    VCS_GIT.lower(): VCS_GIT,
}
# The result of parsing Subversion's [auto-props] setting.
svn_auto_props_map = None

logger = logging.getLogger(__package__)


def StatusUpdate(msg):
    """
    Print a status message to stdout.
    If 'verbosity' is greater than 0, print the message.
    Args:
        msg: The string to print.
    """
    if verbosity > 0:
        logger.info(msg)


def ErrorExit(msg):
    """Print an error message to stderr and exit."""
    raise Exception(msg)


def EncodeMultipartFormData(fields, files):
    """
    Encode form fields for multipart/form-data.
    Args:
        fields: A sequence of (name, value) elements for regular form fields.
        files: A sequence of (name, filename, value) elements for data to be uploaded as files.
    Returns:
        (content_type, body) ready for httplib.HTTP instance.
    Source:
        http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/146306
    """
    BOUNDARY = '-M-A-G-I-C---B-O-U-N-D-A-R-Y-'
    CRLF = '\r\n'
    lines = []
    for (key, value) in fields:
        lines.append('--' + BOUNDARY)
        lines.append('Content-Disposition: form-data; name="%s"' % key)
        lines.append('')
        # if isinstance(value, str):
        #     value = value.encode('utf-8')
        lines.append(value)
    for (key, filename, value) in files:
        lines.append('--' + BOUNDARY)
        lines.append('Content-Disposition: form-data; name="%s"; filename="%s"' %
                     (key, filename))
        lines.append('Content-Type: %s' % GetContentType(filename))
        lines.append('')
        # if isinstance(value, str):
        #     value = value.encode('utf-8')
        lines.append(value)
    lines.append('--' + BOUNDARY + '--')
    lines.append('')
    body = CRLF.join(lines)
    content_type = 'multipart/form-data; boundary=%s' % BOUNDARY
    return content_type, body


def GetContentType(filename):
    """Helper to guess the content-type from the filename."""
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'


# Use a shell for subcommands on Windows to get a PATH search.
use_shell = sys.platform.startswith("win")


def RunShellWithReturnCode(command, print_output=False,
                           universal_newlines=True,
                           env=os.environ):
    """
    Executes a command and returns the output from stdout and the return code.
    Args:
        command: Command to execute.
        print_output: If True, the output is printed to stdout. If False, both stdout and stderr are ignored.
        universal_newlines: Use universal_newlines flag (default: True).
    Returns:
        Tuple (output, return code)
    """
    logger.info("Running %s", command)
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         shell=use_shell, universal_newlines=universal_newlines,
                         env=env)
    if print_output:
        output_array = []
        while True:
            line = p.stdout.readline()
            if not line:
                break
            logger.info(line.strip("\n"))
            output_array.append(line)
        output = "".join(output_array)
    else:
        output = p.stdout.read()
    p.wait()
    errout = p.stderr.read()
    if print_output and errout:
        print(sys.stderr, errout)
    p.stdout.close()
    p.stderr.close()
    return output, p.returncode


def RunShell(command, silent_ok=False, universal_newlines=True,
             print_output=False, env=os.environ):
    data, retcode = RunShellWithReturnCode(command, print_output,
                                           universal_newlines, env)
    if retcode:
        ErrorExit("Got error status from %s:\n%s" % (command, data))
    if not silent_ok and not data:
        ErrorExit("No output from %s" % command)
    return data


# handle svn info for all the file
def handleCharSet(data):
    isFirst = True
    temp = ''
    ret = ''
    for line in data.splitlines(True):
        if line.startswith('Index:') or line.startswith('Property changes on:'):
            if isFirst:
                temp += line
                isFirst = False
            else:
                ret += temp
                temp = line
        else:
            temp += line
    ret += temp
    return ret


class CharSetConverter:
    @staticmethod
    def autoConvert(src_str):
        encoding = 'utf-8'
        try:
            src_str.decode('utf-8')
        except UnicodeDecodeError:
            encoding = 'gbk'
        retStr = src_str.decode(encoding)
        return retStr


class VersionControlSystem(object):
    """Abstract base class providing an interface to the VCS."""

    def __init__(self, options):
        """
        Constructor.
        Args:
            options: Command line options.
        """
        self.options = options

    def PostProcessDiff(self, diff):
        """Return the diff with any special post processing this VCS needs, e.g. to include an svn-style "Index:"."""
        return diff

    def GenerateDiff(self, args):
        """
        Return the current diff as a string.
        Args:
            args: Extra arguments to pass to the diff command.
        """
        raise NotImplementedError(
            "abstract method -- subclass %s must override" % self.__class__)

    def GetUnknownFiles(self):
        """Return a list of files unknown to the VCS."""
        raise NotImplementedError(
            "abstract method -- subclass %s must override" % self.__class__)

    def CheckForUnknownFiles(self):
        """Show an "are you sure?" prompt if there are unknown files."""
        unknown_files = self.GetUnknownFiles()
        if unknown_files:
            logger.info("The following files are not added to version control:")
            for line in unknown_files:
                print(line)
            prompt = "Are you sure to continue?(y/N) "
            answer = input(prompt).strip()
            if answer != "y":
                ErrorExit("User aborted")

    def GetBaseFile(self, filename):
        """
        Get the content of the upstream version of a file.
        Returns:
            A tuple (base_content, new_content, is_binary, status)
            base_content: The contents of the base file.
            new_content: For text files, this is empty. For binary files, this is the contents of the new file, since the diff output won't contain information to reconstruct the current file.
            is_binary: True iff the file is binary.
            status: The status of the file.
        """
        raise NotImplementedError(
            "abstract method -- subclass %s must override" % self.__class__)

    def GetBaseFiles(self, diff):
        """
        Helper that calls GetBase file for each file in the patch.
        Returns:
            A dictionary that maps from filename to GetBaseFile's tuple.  Filenames are retrieved based on lines that start with "Index:" or "Property changes on:".
        """
        files = {}
        for line in diff.splitlines(True):
            if line.startswith('Index:') or line.startswith('Property changes on:'):
                unused, filename = line.split(':', 1)
                # On Windows if a file has property changes its filename uses '\'
                # instead of '/'.
                filename = filename.strip().replace('\\', '/')
                files[filename] = self.GetBaseFile(filename)
        return files

    def GetBaseFilesName(self, diff):
        """
        Helper that calls GetBase file for each file in the patch.
        Returns:
            A dictionary that maps from filename to GetBaseFile's tuple.  Filenames are retrieved based on lines that start with "Index:" or "Property changes on:".
        """
        files = {}
        for line in diff.splitlines(True):
            if line.startswith('Index:') or line.startswith('Property changes on:'):
                unused, filename = line.split(':', 1)
                # On Windows if a file has property changes its filename uses '\'
                # instead of '/'.
                filename = filename.strip().replace('\\', '/')
                # files[filename] = self.GetBaseFile(filename)
                files[filename] = ""
        return files

    def UploadBaseFiles(self, issue, rpc_server, patch_list, patchset, options,
                        files):
        """Uploads the base files (and if necessary, the current ones as well)."""

        def UploadFile(filename, file_id, content, is_binary, status, is_base):
            """Uploads a file to the server."""
            file_too_large = False
            if is_base:
                type = "base"
            else:
                type = "current"
            if len(content) > MAX_UPLOAD_SIZE:
                print("Not uploading the %s file for %s because it's too large." % (type, filename))
                file_too_large = True
                content = ""
            checksum = hashlib.md5(content).hexdigest()
            if options.verbose > 0 and not file_too_large:
                print("Uploading %s file for %s" % (type, filename))
            url = "/%d/upload_content/%d/%d" % (int(issue), int(patchset), file_id)
            form_fields = [("filename", filename),
                           ("status", status),
                           ("checksum", checksum),
                           ("is_binary", str(is_binary)),
                           ("is_current", str(not is_base)),
                           ]
            if file_too_large:
                form_fields.append(("file_too_large", "1"))
            if options.email:
                form_fields.append(("user", options.email))
            ctype, body = EncodeMultipartFormData(form_fields,
                                                  [("data", filename, content)])
            response_body = rpc_server.Send(url, body, content_type=ctype)
            if not response_body.startswith("OK"):
                ErrorExit("  --> %s" % response_body)

        patches = dict()
        [patches.setdefault(v, k) for k, v in patch_list]
        for filename in patches.keys():
            base_content, new_content, is_binary, status = files[filename]
            file_id_str = patches.get(filename)
            if file_id_str.find("nobase") != -1:
                base_content = None
                file_id_str = file_id_str[file_id_str.rfind("_") + 1:]
            file_id = int(file_id_str)
            if base_content is not None:
                UploadFile(filename, file_id, base_content, is_binary, status, True)
            if new_content is not None:
                UploadFile(filename, file_id, new_content, is_binary, status, False)

    def IsImage(self, filename):
        """Returns true if the filename has an image extension."""
        mimetype = mimetypes.guess_type(filename)[0]
        if not mimetype:
            return False
        return mimetype.startswith("image/")

    def IsBinary(self, filename):
        """Returns true if the guessed mimetyped isnt't in text group."""
        mimetype = mimetypes.guess_type(filename)[0]
        if not mimetype:
            return False  # e.g. README, "real" binaries usually have an extension
        # special case for text files which don't start with text/
        if mimetype in TEXT_MIMETYPES:
            return False
        return not mimetype.startswith("text/")


class SubversionVCS(VersionControlSystem):
    """Implementation of the VersionControlSystem interface for Subversion."""

    def __init__(self, options):
        super(SubversionVCS, self).__init__(options)
        if self.options.revision:
            match = re.match(r"(\d+)(:(\d+))?", self.options.revision)
            if not match:
                ErrorExit("Invalid Subversion revision %s." % self.options.revision)
            self.rev_start = match.group(1)
            self.rev_end = match.group(3)
        else:
            self.rev_start = self.rev_end = None
        # Cache output from "svn list -r REVNO dirname".
        # Keys: dirname, Values: 2-tuple (ouput for start rev and end rev).
        self.svnls_cache = {}
        # Base URL is required to fetch files deleted in an older revision.
        # Result is cached to not guess it over and over again in GetBaseFile().
        required = self.options.download_base or self.options.revision is not None
        self.svn_base = self._GuessBase(required)

    def GuessBase(self, required):
        """Wrapper for _GuessBase."""
        return self.svn_base

    def _GuessBase(self, required):
        """
        Returns the SVN base URL.
        Args:
            required: If true, exits if the url can't be guessed, otherwise None is returned.
        """
        info = RunShell(["svn", "info", self.options.path])
        isFile = False
        for line in info.splitlines():
            words = line.split()
            if len(words) == 2 and words[0] == "URL:":
                url = words[1]
                scheme, netloc, path, params, query, fragment = urlparse(url)
                username, netloc = urllib.split(netloc)
                if username:
                    logger.info("Removed username from base URL")
                if netloc.endswith("svn.python.org"):
                    if netloc == "svn.python.org":
                        if path.startswith("/projects/"):
                            path = path[9:]
                    elif netloc != "pythondev@svn.python.org":
                        ErrorExit("Unrecognized Python URL: %s" % url)
                    base = "http://svn.python.org/view/*checkout*%s/" % path
                    logger.info("Guessed Python base = %s", base)
                elif netloc.endswith("svn.collab.net"):
                    if path.startswith("/repos/"):
                        path = path[6:]
                    base = "http://svn.collab.net/viewvc/*checkout*%s/" % path
                    logger.info("Guessed CollabNet base = %s", base)
                elif netloc.endswith(".googlecode.com"):
                    path = path + "/"
                    base = urlunparse(("http", netloc, path, params, query, fragment))
                    logger.info("Guessed Google Code base = %s", base)
                else:
                    if isFile:
                        path = path[:path.rfind("/")]
                    path = path + "/"
                    base = urlunparse((scheme, netloc, path, params, query, fragment))
                    logger.info("Guessed base = %s", base)
                return base
            elif line.startswith("Name: ") or line.startswith(
                    "\xe5\x90\x8d\xe7\xa7\xb0: "):  # check target if is a file
                isFile = True
        if required:
            ErrorExit("Can't find URL in output from svn info")
        return None

    def GenerateDiff(self, args):
        if self.options.sponsorfilelist:
            cmd = ["svn", "st"]
        else:
            # check external diff program
            external_diff = False
            logger.info("check vim diff")
            home = os.path.expanduser("~")
            config = os.path.join(home, ".subversion/config")
            if os.path.isfile(config):
                with open(config) as f:
                    for line in f:
                        if line.strip().startswith('diff-cmd'):
                            external_diff = True
                            break
            # set command
            cmd = ["svn", "diff"]
            if external_diff:
                if os.name == 'posix' and os.path.exists("/usr/bin/diff"):
                    cmd = ["svn", "diff", "--diff-cmd=/usr/bin/diff"]
                print(
                    "Warning! Your svn diff was replaced by another external diff tool, that may case an error when patch files!")
            if self.options.revision:
                cmd += ["-r", self.options.revision]
        cmd.extend(args)
        data = RunShell(cmd)
        count = 0
        if self.options.sponsorfilelist:
            for line in data.splitlines():
                if line.strip():
                    count += 1
                    break
            if not count:
                ErrorExit("No valid filelist found in output from svn st")
        else:
            for line in data.splitlines():
                if line.startswith("Index:") or line.startswith("Property changes on:"):
                    count += 1
                    logger.info(line)
            if not count:
                ErrorExit("No valid patches found in output from svn diff")
        return data

    def _CollapseKeywords(self, content, keyword_str):
        """Collapses SVN keywords."""
        # svn cat translates keywords but svn diff doesn't. As a result of this
        # behavior patching.PatchChunks() fails with a chunk mismatch error.
        # This part was originally written by the Review Board development team
        # who had the same problem (http://reviews.review-board.org/r/276/).
        # Mapping of keywords to known aliases
        svn_keywords = {
            # Standard keywords
            'Date': ['Date', 'LastChangedDate'],
            'Revision': ['Revision', 'LastChangedRevision', 'Rev'],
            'Author': ['Author', 'LastChangedBy'],
            'HeadURL': ['HeadURL', 'URL'],
            'Id': ['Id'],
            # Aliases
            'LastChangedDate': ['LastChangedDate', 'Date'],
            'LastChangedRevision': ['LastChangedRevision', 'Rev', 'Revision'],
            'LastChangedBy': ['LastChangedBy', 'Author'],
            'URL': ['URL', 'HeadURL'],
        }

        def repl(m):
            if m.group(2):
                return "$%s::%s$" % (m.group(1), " " * len(m.group(3)))
            return "$%s$" % m.group(1)

        keywords = [keyword
                    for name in keyword_str.split(" ")
                    for keyword in svn_keywords.get(name, [])]
        return re.sub(r"\$(%s):(:?)([^$]+)\$" % '|'.join(keywords), repl, content)

    def GetUnknownFiles(self):
        status = RunShell(["svn", "status", "-q", "--ignore-externals"], silent_ok=True)
        unknown_files = []
        for line in status.split("\n"):
            if line and line[0] == "?":
                unknown_files.append(line)
        return unknown_files

    def ReadFile(self, filename):
        """Returns the contents of a file."""
        file = open(filename, 'rb')
        result = ""
        try:
            result = file.read()
        finally:
            file.close()
        return result

    def GetStatus(self, filename):
        """Returns the status of a file."""
        if not self.options.revision:
            status = RunShell(["svn", "status", "--ignore-externals", filename])
            if not status:
                ErrorExit("svn status returned no output for %s" % filename)
            status_lines = status.splitlines()
            # If file is in a cl, the output will begin with
            # "\n--- Changelist 'cl_name':\n".  See
            # http://svn.collab.net/repos/svn/trunk/notes/changelist-design.txt
            if (len(status_lines) == 3 and
                    not status_lines[0] and
                    status_lines[1].startswith("--- Changelist")):
                status = status_lines[2]
            else:
                status = status_lines[0]
        # If we have a revision to diff against we need to run "svn list"
        # for the old and the new revision and compare the results to get
        # the correct status for a file.
        else:
            dirname, relfilename = os.path.split(filename)
            if dirname not in self.svnls_cache:
                cmd = ["svn", "list", "-r", self.rev_start, dirname or "."]
                out, returncode = RunShellWithReturnCode(cmd)
                if returncode:
                    ErrorExit("Failed to get status for %s." % filename)
                old_files = out.splitlines()
                args = ["svn", "list"]
                if self.rev_end:
                    args += ["-r", self.rev_end]
                cmd = args + [dirname or "."]
                out, returncode = RunShellWithReturnCode(cmd)
                if returncode:
                    ErrorExit("Failed to run command %s" % cmd)
                self.svnls_cache[dirname] = (old_files, out.splitlines())
            old_files, new_files = self.svnls_cache[dirname]
            if relfilename in old_files and relfilename not in new_files:
                status = "D   "
            elif relfilename in old_files and relfilename in new_files:
                status = "M   "
            else:
                status = "A   "
        return status

    def GetBaseFile(self, filename):
        status = self.GetStatus(filename)
        base_content = None
        new_content = None
        # If a file is copied its status will be "A  +", which signifies
        # "addition-with-history".  See "svn st" for more information.  We need to
        # upload the original file or else diff parsing will fail if the file was
        # edited.
        if status[0] == "A" and status[3] != "+":
            # We'll need to upload the new content if we're adding a binary file
            # since diff's output won't contain it.
            mimetype = RunShell(["svn", "propget", "svn:mime-type", filename],
                                silent_ok=True)
            base_content = ""
            is_binary = bool(mimetype) and not mimetype.startswith("text/")
            if is_binary and self.IsImage(filename):
                new_content = self.ReadFile(filename)
        elif (status[0] in ("M", "D", "R") or
              (status[0] == "A" and status[3] == "+") or  # Copied file.
              (status[0] == " " and status[1] == "M")):  # Property change.
            args = []
            if self.options.revision:
                url = "%s/%s@%s" % (self.svn_base, filename, self.rev_start)
            else:
                # Don't change filename, it's needed later.
                url = filename
                args += ["-r", "BASE"]
            cmd = ["svn"] + args + ["propget", "svn:mime-type", url]
            mimetype, returncode = RunShellWithReturnCode(cmd)
            if returncode:
                # File does not exist in the requested revision.
                # Reset mimetype, it contains an error message.
                mimetype = ""
            get_base = False
            is_binary = bool(mimetype) and not mimetype.startswith("text/")
            if status[0] == " ":
                # Empty base content just to force an upload.
                base_content = ""
            elif is_binary:
                if self.IsImage(filename):
                    get_base = True
                    if status[0] == "M":
                        if not self.rev_end:
                            new_content = self.ReadFile(filename)
                        else:
                            url = "%s/%s@%s" % (self.svn_base, filename, self.rev_end)
                            new_content = RunShell(["svn", "cat", url],
                                                   universal_newlines=True, silent_ok=True)
                else:
                    base_content = ""
            else:
                get_base = True
            if get_base:
                if is_binary:
                    universal_newlines = False
                else:
                    universal_newlines = True
                if self.rev_start:
                    # "svn cat -r REV delete_file.txt" doesn't work. cat requires
                    # the full URL with "@REV" appended instead of using "-r" option.
                    url = "%s/%s@%s" % (self.svn_base, filename, self.rev_start)
                    base_content = RunShell(["svn", "cat", url],
                                            universal_newlines=universal_newlines,
                                            silent_ok=True)
                else:
                    base_content = RunShell(["svn", "cat", filename],
                                            universal_newlines=universal_newlines,
                                            silent_ok=True)
                if not is_binary:
                    args = []
                    if self.rev_start:
                        url = "%s/%s@%s" % (self.svn_base, filename, self.rev_start)
                    else:
                        url = filename
                        args += ["-r", "BASE"]
                    cmd = ["svn"] + args + ["propget", "svn:keywords", url]
                    keywords, returncode = RunShellWithReturnCode(cmd)
                    if keywords and not returncode:
                        base_content = self._CollapseKeywords(base_content, keywords)
        else:
            ErrorExit("svn status returned unexpected output: %s" % status)
        return base_content, new_content, is_binary, status[0:5]


# NOTE: The SplitPatch function is duplicated in engine.py, keep them in sync.
def SplitPatch(data):
    """
    Splits a patch into separate pieces for each file.
    Args:
        data: A string containing the output of svn diff.
    Returns:
        A list of 2-tuple (filename, text) where text is the svn diff output pertaining to filename.
    """
    patches = []
    filename = None
    diff = []
    for line in data.splitlines(True):
        new_filename = None
        if line.startswith('Index:'):
            unused, new_filename = line.split(':', 1)
            new_filename = new_filename.strip()
        elif line.startswith('Property changes on:'):
            unused, temp_filename = line.split(':', 1)
            # When a file is modified, paths use '/' between directories, however
            # when a property is modified '\' is used on Windows.  Make them the same
            # otherwise the file shows up twice.
            temp_filename = temp_filename.strip().replace('\\', '/')
            if temp_filename != filename:
                # File has property changes but no modifications, create a new diff.
                new_filename = temp_filename
        if new_filename:
            if filename and diff:
                patches.append((filename, ''.join(diff)))
            filename = new_filename
            diff = [line]
            continue
        if diff is not None:
            diff.append(line)
    if filename and diff:
        patches.append((filename, ''.join(diff)))
    return patches


def UploadSeparatePatches(issue, rpc_server, patchset, data, options):
    """
    Uploads a separate patch for each file in the diff output.
    Returns a list of [patch_key, filename] for each file.
    """
    patches = SplitPatch(data)
    rv = []
    for patch in patches:
        if len(patch[1]) > MAX_UPLOAD_SIZE:
            print("Not uploading the patch for " + patch[0] + " because the file is too large.")
            continue
        form_fields = [("filename", patch[0])]
        if not options.download_base:
            form_fields.append(("content_upload", "1"))
        files = [("data", "data.diff", patch[1])]
        ctype, body = EncodeMultipartFormData(form_fields, files)
        url = "/%d/upload_patch/%d" % (int(issue), int(patchset))
        print("Uploading patch for " + patch[0])
        response_body = rpc_server.Send(url, body, content_type=ctype)
        lines = response_body.splitlines()
        if not lines or lines[0] != "OK":
            ErrorExit("  --> %s" % response_body)
        rv.append([lines[1], patch[0]])
    return rv


def GuessVCSName(path):
    """
    Helper to guess the version control system.
    This examines the current directory, guesses which VersionControlSystem we're using, and returns an string indicating which VCS is detected.
    Returns:
        A pair (vcs, output).  vcs is a string indicating which VCS was detected and is one of VCS_GIT, VCS_MERCURIAL, VCS_SUBVERSION, or VCS_UNKNOWN.
        output is a string containing any interesting output from the vcs detection routine, or None if there is nothing interesting.
    """
    # Subversion has a .svn or _svn in all working directories.
    if os.path.isdir(path + '/.svn') or os.path.isdir(path + '/_svn'):
        logger.info("Guessed VCS = Subversion")
        return VCS_SUBVERSION, None
    # Subversion
    try:
        out, returncode = RunShellWithReturnCode(["svn", "info", path])
        if returncode == 0:
            return VCS_SUBVERSION, out.strip()
    except OSError as message:
        # if errno != 2:  # ENOENT -- they don't have subversion installed.
        raise
    # Mercurial has a command to get the base directory of a repository
    # Try running it, but don't die if we don't have hg installed.
    # NOTE: we try Mercurial first as it can sit on top of an SVN working copy.
    try:
        out, returncode = RunShellWithReturnCode(["hg", "root"])
        if returncode == 0:
            return VCS_MERCURIAL, out.strip()
    except OSError as message:
        # if errno != 2:  # ENOENT -- they don't have hg installed.
        raise
    # Git has a command to test if you're in a git tree.
    # Try running it, but don't die if we don't have git installed.
    try:
        out, returncode = RunShellWithReturnCode(["git", "rev-parse",
                                                  "--is-inside-work-tree"])
        if returncode == 0:
            return VCS_GIT, None
    except OSError as message:
        # if errno != 2:  # ENOENT -- they don't have git installed.
        raise
    return VCS_UNKNOWN, None


def GuessVCS(options):
    """
    Helper to guess the version control system.
    This verifies any user-specified VersionControlSystem (by command line or environment variable).
    If the user didn't specify one, this examines the current directory, guesses which VersionControlSystem we're using, and returns an instance of the appropriate class.
    Exit with an error if we can't figure it out.
    Returns:
        A VersionControlSystem instance. Exits if the VCS can't be guessed.
    """
    vcs = options.vcs
    if not vcs:
        vcs = os.environ.get("CODEREVIEW_VCS")
    if vcs:
        v = VCS_ABBREVIATIONS.get(vcs.lower())
        if v is None:
            ErrorExit("Unknown version control system %r specified." % vcs)
        (vcs, extra_output) = (v, None)
    else:
        (vcs, extra_output) = GuessVCSName(options.path)
    if vcs == VCS_SUBVERSION:
        return SubversionVCS(options)
    # elif vcs == VCS_MERCURIAL:
    #     if extra_output is None:
    #       extra_output = RunShell(["hg", "root"]).strip()
    #     return MercurialVCS(options, extra_output)
    #   elif vcs == VCS_GIT:
    #     return GitVCS(options)
    ErrorExit(("Could not guess version control system. "
               "Are you in a working copy directory?"))


# -------------------------------------------------------------------
# BEGIN added
# -------------------------------------------------------------------
def IsBinaryFile(filepath):
    isBinary = False
    lastdotindex = filepath.rfind('.')
    suffix = ''
    if 0 <= lastdotindex <= len(filepath) - 2:
        suffix = filepath[(lastdotindex + 1):]
    if suffix != '' and suffix.lower() in IGNORE_FILE_SUFFIX:
        isBinary = True
    return isBinary


def TencentAccount(users):
    """append '@tencent.com' to each user if necessary"""
    if users is None:
        return None
    user_list = []
    for user in users.split(','):
        if user.endswith('@tencent.com'):
            user = user.split('@')[0]
        if len(user) == 0:
            ErrorExit("Invalid user account : %s" % user)
        user_list.append(user)
    email_list = ['%s@tencent.com' % user for user in user_list]
    # print  ','.join(email_list)
    return ','.join(email_list)


def ChooseEncodingWhenAmbiguous(encodings):
    """Choose encoding when multiple encoding are available"""
    sysencoding = sys.stdin.encoding.lower()
    guesscoding = 'gbk'
    if sysencoding == 'utf-8':
        guesscoding = sysencoding
    print('Automatic encoding detection fails due to ambiguity, is %s ?\n' % guesscoding)
    num_encoding = len(encodings)
    mesg = ' '.join(['%s(%s)' % (i, encodings[i]) for i in range(num_encoding)])
    while True:
        choose = input('Please choose the encoding number : %s' % mesg)
        try:
            choose = int(choose)
        except:
            print('Invalid input, please input an integer')
            continue
        if 0 <= choose < num_encoding:
            return choose
        else:
            print('Invalid input, the interger is out of bound')


def ChooseEncodingWhenFail(encodings):
    """Choose encoding when no encoding is available"""
    print('Automatic encoding detection fails.You can ignore decoding')
    print('by enforing use a specified encoding''')
    num_encoding = len(encodings)
    mesg = ' '.join(['%s(%s)' % (i, encodings[i]) for i in range(num_encoding)])
    mesg += ' %s(QUIT)' % (num_encoding)
    while True:
        choose = input('Please choose the encoding number : %s' % mesg)
        try:
            choose = int(choose)
        except:
            print('Invalid input, please input an integer')
            continue
        if 0 <= choose < num_encoding:
            return choose
        elif choose == num_encoding:
            return
        else:
            print('Invalid input, the interger is out of bound')


def FilterData(data, files):
    files = FilterFiles(files)
    new_data = []
    keep_line = False
    curfiles = []
    lastline = ''
    currfiles = {}
    for line in data.splitlines(True):
        if line.startswith('Index:'):
            unused, filename = line.split(':', 1)
            filename = filename.strip().replace('\\', '/')
            if filename in files and (
                    os.path.isfile(filename) or not os.path.exists(filename)) and filename not in currfiles:
                currfiles[filename] = ""
                if IsBinaryFile(filename):
                    keep_line = False
                    new_data.append(BinaryFileDiff(filename))
                else:
                    keep_line = True
                filename = removeFileBase(filename)
                curfiles.append(filename)
                line = 'Index: ' + filename + '\r\n'
            else:
                keep_line = False
        # elif line.startswith('Property changes on:'):
        #  keep_line = False
        if keep_line:
            if line.startswith(
                    '--- ') and lastline.strip() == '===================================================================':
                line = CheckCopyfrom(line)
            new_data.append(line)
        lastline = line
    data = ''.join(new_data)
    return data, curfiles


def BinaryFileDiff(filepath):
    data = ''
    delFile = False
    revision = 'none'
    status = RunShell(["svn", "status", "-q", "--ignore-externals", filepath], silent_ok=True)
    for line in status.split("\n"):
        if line.startswith('D') and line[4:].strip().replace('\\', '/') == filepath:
            delFile = True
            break
    if delFile:
        info, retcode = RunShellWithReturnCode(["svn", "info", filepath])
        if retcode:
            ErrorExit("Failed to get info for %s." % filepath)
        for line in info.splitlines():
            words = line.split(': ')
            if len(words) == 2:
                if words[0] == "Last Changed Rev":
                    revision = words[1]
                    break
    data = data + ''.join(["Index: ", removeFileBase(filepath),
                           "\r\n===================================================================\r\n--- ",
                           filepath + "\t(revision " + revision + ")\r\n",
                           "+++ ", filepath, "\t(working copy)\r\n@@ ",
                           "-1,1 +0,0 @@\r\n-\r\n" if delFile else "-0,0 +1,0 @@\r\n+\r\n"])
    return data


def FilterFiles(files):
    if options.files:
        keep_list = []
        for keep in options.files.split(";"):
            if keep == '':
                continue
            keep = options.path + '/' + keep
            keep = "/".join(keep.split("\\"))
            keep_list.append(keep)
        keep_files = {}
        for f, info in files.items():
            filepath = f if options.path != '.' else (options.path + '/' + f)
            if isSubFile(keep_list, filepath):
                keep_files[f] = info
        files = keep_files
    # filter files using --skip
    if options.skip:
        skip_list = []
        for skip in options.skip.split(";"):
            skip = options.path + '/' + skip
            skip = "/".join(skip.split("\\"))
            if skip.find("/") == 0:
                skip = skip[1:]
            skip_list.append(skip)
        keep_files = {}
        for f, info in files.items():
            skip_flag = isSubFile(skip_list, f)
            if not skip_flag:
                keep_files[f] = info
        files = keep_files
    return files


# Added by lekkoli
# the parm 'leftLine' should like: --- bc1/nice2.txt  (revision 458)
def CheckCopyfrom(leftLine):
    filePath = leftLine[4:leftLine.index('(')].strip()
    info, retcode = RunShellWithReturnCode(["svn", "info", filePath])
    if retcode or not info:
        return leftLine
    retLine = '--- '
    isCopy = False
    curRev = -1
    for line in info.splitlines():
        words = line.split(': ')
        if len(words) == 2:
            if words[0] == "Copied From URL":
                isCopy = True
                retLine += FormatSvnUrl(words[1])
            elif words[0] == "Copied From Rev":
                retLine += ('\t(revision ' + words[1] + ')\r\n')
                break
            elif words[0] == "Revision":
                curRev = words[1]
    if isCopy:
        return retLine
    elif curRev > 0:
        return retLine + filePath + "\t(revision " + curRev + ")\r\n"
    return leftLine


def CheckCopyFile(files):
    curFileNames = files
    data = ''
    status = RunShell(["svn", "status", "-q", "--ignore-externals", options.path], silent_ok=True)
    filterFileNames = [] if options.files is None else options.files.split(";")
    for line in status.split("\n"):
        if line.startswith("A  +"):
            filepath = line[4:].strip().replace('\\', '/')
            filename = removeFileBase(filepath)
            if filename not in curFileNames and (len(filterFileNames) == 0 or filename in filterFileNames) and (
                    len(options.args) == 0 or isSubFile(options.args, filepath)):
                data += ''.join(["Index: ", filename,
                                 "\r\n===================================================================\r\n",
                                 CheckCopyfrom("--- " + filepath + "\t(revision -1)\r\n"),
                                 "+++ ", filepath, "\t(working copy)\r\n"])
    return data


def removeFileBase(filepath):
    if options.path != '.':
        filename = filepath[len(options.path) + 1:]
        if len(filename) == 0:
            return filepath[filepath.rfind('/') + 1:]
        else:
            return filename
    return filepath


def isSubFile(roots, filepath):
    for root in roots:
        if root == filepath or (root == './' + filepath) or (os.path.isdir(root) and filepath.startswith(root)):
            return True
    return False


def FormatSvnUrl(url):
    return re.sub("svn\+ssh://(\w*?@)?", "http://", url)


# Added by hsiaokangliu
def TryEncode(instring, description=None):
    """Try to use (assci, gbk, utf-8) encoding to decode data. other encodings are not supported currently."""
    try:
        unicode_string = instring.decode('ascii')
    except Exception as e:
        encodings = ['gbk', 'utf-8']
        result = []
        for enc in encodings:
            try:
                result.append(instring.decode(enc))
            except Exception as e:
                pass
        if len(result) > 1:
            print('ERROR in processing %s' % description)
            index = 1  # ChooseEncodingWhenAmbiguous(encodings) #有bug，下屏蔽，默认utf-8
            unicode_string = result[index]
        elif len(result) == 0:
            print('ERROR in processing %s' % description)
            index = ChooseEncodingWhenFail(encodings)
            unicode_string = instring.decode(encodings[index], 'replace')
        else:
            unicode_string = result[0]
    return unicode_string.encode('utf-8')


# -------------------------------------------------------------------
# END added
# -------------------------------------------------------------------
# -------------------------------------------------------------------
# BEGIN Tencent Ldap
# -------------------------------------------------------------------
'''
def TencentLdapAuth(server, username, password):
  """ do simple  authentication via http login"""
  if not username or not password:
    return False
  field_form = [('username', username), ('password', password)]
  field_form.append(DEFAULT_NEEDED_PARAMETERS)
  ldapRequest = GetRequest(server, 'websvn/ldap.jsp', field_form)
  try:
    ldapResponse = urllib2.urlopen(ldapRequest)
    global ldapCookie
    ldapCookie = ldapResponse.headers.get('Set-Cookie')
    response = ldapResponse.read()
    if(response.strip() == '1'):
        return True
    else:
        if(response.find('775') != -1):
           ErrorExit("'%s' is locked, please contact 8000." % username)
        return False
    ldapResponse.close()
  except Exception, e:
    print 'Exception in account authentication : %s' %e
    return False
'''
'''
def ForceLdapAuth(server, username):
  """Prompts the user for a username and password, and do authentication."""
  password = ''
  i = 0
  while not TencentLdapAuth(server, username, password):
      i = i+1
      if(i>1):
          print "Authentication failed."
      if(i<4):
          password = getpass.getpass("Input outlook password for %s: " % username)
      else:
          ErrorExit("Please check the username is '%s' ?" % username)
'''


def TencentFormatAccount(users):
    """delete '@tencent.com' to each user if necessary and jion in ';'"""
    if users is None:
        return None
    user_list = []
    for user in users.split(','):
        if user.endswith('@tencent.com'):
            user = user.split('@')[0]
        if len(user) == 0:
            ErrorExit("Invalid user account : %s" % user)
        user_list.append(user)
    return ';'.join(user_list)


# -------------------------------------------------------------------
# END Tencent Ldap
# -------------------------------------------------------------------
def LoadSubversionAutoProperties():
    """
    Returns the content of [auto-props] section of Subversion's config file as a dictionary.
    Returns:
        A dictionary whose key-value pair corresponds the [auto-props] section's key-value pair.
    In following cases, returns empty dictionary:
        - config file doesn't exist, or
        - 'enable-auto-props' is not set to 'true-like-value' in [miscellany].
    """
    # Todo(hayato): Windows users might use different path for configuration file.
    subversion_config = os.path.expanduser("~/.subversion/config")
    if not os.path.exists(subversion_config):
        return {}
    config = configparser.ConfigParser()
    config.read(subversion_config)
    if (config.has_section("miscellany") and
            config.has_option("miscellany", "enable-auto-props") and
            config.getboolean("miscellany", "enable-auto-props") and
            config.has_section("auto-props")):
        props = {}
        for file_pattern in config.options("auto-props"):
            props[file_pattern] = ParseSubversionPropertyValues(
                config.get("auto-props", file_pattern))
        return props
    else:
        return {}


def ParseSubversionPropertyValues(props):
    """
    Parse the given property value which comes from [auto-props] section and returns a list whose element is a (svn_prop_key, svn_prop_value) pair.
    See the following doctest for example.
    >>> ParseSubversionPropertyValues('svn:eol-style=LF')
        [('svn:eol-style', 'LF')]
    >>> ParseSubversionPropertyValues('svn:mime-type=image/jpeg')
        [('svn:mime-type', 'image/jpeg')]
    >>> ParseSubversionPropertyValues('svn:eol-style=LF;svn:executable')
        [('svn:eol-style', 'LF'), ('svn:executable', '*')]
    """
    key_value_pairs = []
    for prop in props.split(";"):
        key_value = prop.split("=")
        assert len(key_value) <= 2
        if len(key_value) == 1:
            # If value is not given, use '*' as a Subversion's convention.
            key_value_pairs.append((key_value[0], "*"))
        else:
            key_value_pairs.append((key_value[0], key_value[1]))
    return key_value_pairs


def GetSubversionPropertyChanges(filename):
    """
    Return a Subversion's 'Property changes on ...' string, which is used in the patch file.
    Args:
        filename: filename whose property might be set by [auto-props] config.
    Returns:
        A string like 'Property changes on |filename| ...' if given |filename| matches any entries in [auto-props] section. None, otherwise.
    """
    global svn_auto_props_map
    if svn_auto_props_map is None:
        svn_auto_props_map = LoadSubversionAutoProperties()
    all_props = []
    for file_pattern, props in svn_auto_props_map.items():
        if fnmatch.fnmatch(filename, file_pattern):
            all_props.extend(props)
    if all_props:
        return FormatSubversionPropertyChanges(filename, all_props)
    return None


def FormatSubversionPropertyChanges(filename, props):
    """
    Returns Subversion's 'Property changes on ...' strings using given filename and properties.
    Args:
        filename: filename
        props: A list whose element is a (svn_prop_key, svn_prop_value) pair.
    Returns:
        A string which can be used in the patch file for Subversion.
    See the following doctest for example.
    >>> print FormatSubversionPropertyChanges('foo.cc', [('svn:eol-style', 'LF')])
        Property changes on: foo.cc
        ___________________________________________________________________
        Added: svn:eol-style
        + LF
        <BLANKLINE>
    """
    prop_changes_lines = [
        "Property changes on: %s" % filename,
        "___________________________________________________________________"]
    for key, value in props:
        prop_changes_lines.append("Added: " + key)
        prop_changes_lines.append("   + " + value)
    return "\n".join(prop_changes_lines) + "\n"


def GetRequest(server, url, field_form=None, data=None, content_type=None, accept_type=None):
    if not server:
        server = DEFAULT_REVIEW_SERVER
    url = "%s/%s" % (server, url)
    if not url.startswith('http://'):
        url = 'http://%s' % url
    if field_form:
        url += "?" + urlencode(field_form)
        # url += "?" + urllib.parse.unquote_plus(urlencode(field_form))
    request = urllib.request.Request(url, data)
    if content_type:
        request.add_header("Content-Type", str(content_type))
    if accept_type:
        request.add_header("Accept", str(accept_type))
    return request


def OpenHttp(server, url, field_form=None, data=None, content_type=None, accept_type=None):
    tries = 0
    while True:
        tries += 1
        try:
            response = urllib.request.urlopen(GetRequest(server, url, field_form, data, content_type, accept_type))
            result = response.read()
            response.close()
            return result.decode('utf-8')
        except urllib.error.HTTPError as e:
            if tries > 3:
                ErrorExit("Can't connect to server by URL: http://%s/%s." % (server, url))
        except urllib.error.URLError as e:
            if tries > 3:
                ErrorExit("Can't connect to server by URL: http://%s/%s." % (server, url))


# -------------------------------------------------------------------
# BEGIN Send Comments
# -------------------------------------------------------------------
class CommnetSender:
    def __init__(self, options):
        self.options = options

    # send commets for a cr request
    def SendComment(self):
        if self.options.issue:
            with codecs.open(self.options.comments, 'r', 'utf-8') as f:
                fp = f.read()
                cmts = json.load(fp)
            # get patch set
            form_field = [("requestId", self.options.issue), ("username", username)]
            ret = OpenHttp(options.server, "tcr-qs/t/tcr/web/endpoint/c/request/getRequestPatchSetById", form_field)
            patchs = json.loads(ret)
            if not patchs["successfully"]:
                ErrorExit("Fetch patch set fail, please check your issue id.")
            patchSet = patchs["fileSets"][-1]
            self.fileList = patchSet["fileList"]
            self.author = patchSet["author"]
            print("Sending comments...")
            # send commets
            for cmt in cmts["comments"]:
                self._SendComment(cmt)
            # send summary
            self._SendSummary(cmts["summary"])
        else:
            ErrorExit("Parameter '--commets' must be used with '-i'.")
        print("Comments sending has been done.")

    def _SendSummary(self, summary):
        form_field = [("requestId", options.issue), ("parentId", 0), ("content", summary), ("username", username)]
        ret = OpenHttp(options.server, "tcr-qs/t/comment/c/comment/addRequestComment", form_field, "",
                       accept_type="application/json;charset=utf-8")
        if not json.loads(ret)["successfully"]:
            print("Warning, send summary comment error.")

    def _SendComment(self, cmt):
        url = cmt["file"]
        url = FormatSvnUrl(url)
        for patch in self.fileList:
            curUrl = patch["fileSvnUrl"]
            if curUrl[curUrl.index("}") + 1:] == url:
                # send
                if cmt["type"] != '3':
                    cmt["type"] = '2'
                form_field = [("creatorName", username), ("bugLevel", cmt["type"]), ("content", cmt["comment"]),
                              ("startLine", cmt["line"]), ("revision", 0),
                              ("toNames", self.author), ("url", curUrl), ("requestId", self.options.issue),
                              ("sendRtx", False), ("endLine", cmt["line"]), ("revisionStr", 0)]
                ret = OpenHttp(options.server, "tcr-qs/t/comment/c/comment/addComment4iFrameFormPost", form_field, "",
                               accept_type="application/json;charset=utf-8")
                if ret.find('"successfully":true') == -1:
                    print("Warning, send comment error: \r\n" + str(cmt) + "\r\n.")
                break
                # -------------------------------------------------------------------


# END Send Comments
# -------------------------------------------------------------------
def getParser():
    """get a new parser that deleted something"""
    ps = optparse.OptionParser(usage=
                               "%prog [options] [-- diff_options] [path...]\r\n" +
                               "           You can directly pass multiple paths in the end of cmd, but these paths must be relative path\r\n" +
                               "       or  You can use parameter [--files \"path1;path2;,,,\"] to send Multi-Paths request")
    # Logging
    group = ps.add_option_group("Logging options")
    group.add_option("-q", "--quiet", action="store_const", const=0,
                     dest="verbose", help="Print errors only.")
    group.add_option("-v", "--verbose", action="store_const", const=2,
                     dest="verbose", default=1,
                     help="Print info level logs (default).")
    group.add_option("--noisy", action="store_const", const=3,
                     dest="verbose", help="Print all logs.")
    # Review server
    group = ps.add_option_group("Review server options")
    group.add_option("-s", "--server", action="store", dest="server",
                     default=DEFAULT_REVIEW_SERVER,
                     metavar="SERVER",
                     help=("The server to upload to. The format is host[:port]. "
                           "Defaults to '%default'."))
    group.add_option("-e", "--email", action="store", dest="email",
                     metavar="EMAIL", default=None,
                     help="The username to use. Will prompt if omitted.")
    # Issue
    group = ps.add_option_group("Request options")
    group.add_option("-m", "--message", action="store", dest="message",
                     metavar="MESSAGE", default=None,
                     help="the request's subject. e.g., tcr.py -m \"your request's subject\" ")
    group.add_option("-d", "--description", action="store", dest="description",
                     metavar="DESCRIPTION", default=None,
                     help="Optional description when creating an issue. e.g. tcr.py -d \"your description about your request.\" ")
    group.add_option("-f", "--description_file", action="store",
                     dest="description_file", metavar="DESCRIPTION_FILE",
                     default=None,
                     help="Optional path of a file that contains "
                          "the description when creating an issue. e.g. tcr.py -f your_description_file")
    group.add_option("-r", "--reviewers", action="store", dest="reviewers",
                     metavar="REVIEWERS", default=None,
                     help="Add reviewers (comma separated email addresses). e.g. tcr.py -r \"tom;jack;jimmy\"")
    group.add_option("-c", "--cc", action="store", dest="cc",
                     metavar="CC", default=None,
                     help="Add CC (comma separated email addresses). e.g. tcr.py -c \"tom;jacky;lucky\"")
    group.add_option("--mp", "--multipass", action='store_true', dest='multi_pass',
                     default=False,
                     help='multi judges pass through this code review, e.g. tcr.py --mp ')
    # Upload options
    group = ps.add_option_group("Patch options")
    group.add_option("-i", "--issue", type="int", action="store",
                     metavar="ISSUE", default=None,
                     help="Issue number to which to add. Defaults to new issue. e.g., tcr.py -i 123456")
    group.add_option('--skip', action='store', dest='skip',
                     help='skip specified files or dirs when processing. e.g., tcr.py --skip "afile;bfiles"')
    group.add_option('--comments', action='store', dest='comments',
                     help='send comments for a code reivew request. e.g., tcr.py -i 89 --comments "/tmp/upload-scan-result.json"')
    group.add_option('--files', action='store', dest='files',
                     help='only process specified files or dirs. e.g., tcr.py --files "afile;bfiles"')
    # call server options
    # group = ps.add_option_group("Ask Server Options")
    # group.add_option("--encoding", action="store", dest="encoding",
    #            help="Assign the patch's encoding.")
    # sponsor third parties options
    group = ps.add_option_group("Sponsor Fileslist Options")
    group.add_option("--sf", "--sponsorfilelist", action='store_true', dest='sponsorfilelist', default=False,
                     help='sponsor third parties, e.g. tcr.py --sf ')
    # get software version
    group = ps.add_option_group("Version Info")
    group.add_option("--version", action='store_const', dest='version_info', const=REAL_VERSION,
                     help='get software version, e.g. tcr.py --version ')
    return ps


def setInitparser(parser):
    """init all options"""
    parser.add_option("--vcs", action="store", dest="vcs",
                      metavar="VCS", default=None,
                      help=("Version control system (optional, usually upload.py "
                            "already guesses the right VCS)."))
    parser.add_option("--rev", action="store", dest="revision",
                      metavar="REV", default=None,
                      help="Base revision/branch/tree to diff against. Use "
                           "rev1:rev2 range to review already committed changeset.")
    parser.add_option("--download_base", action="store_true",
                      dest="download_base", default=False,
                      help="Base files will be downloaded by the server "
                           "(side-by-side diffs may not work on files with CRs).")
    return parser


def ValidataVersion():
    form_filed = [("version", VERSION)]
    # form_filed.append(DEFAULT_NEEDED_PARAMETERS)
    # versionInfo = OpenHttp(options.server, "websvn/ldap.jsp", form_filed).strip()
    versionInfo = OpenHttp(options.server, "tcr-qs/t/rc-biz/c/client/checkPythonClientVersion", form_filed).strip().replace('"', '')
    if versionInfo:
        ErrorExit(versionInfo.replace("  ", "\r\n"))


def GetCodeOwners(svnurl):
    owners = ''
    if svnurl:
        # form_filed = [("version", VERSION)]
        # form_filed.append(DEFAULT_NEEDED_PARAMETERS)
        # owners = OpenHttp(options.server, 'websvn/internal/api/getCodeOwners', form_filed, data=svnurl)
        form_filed = [("rootUrl", svnurl)]
        owner = OpenHttp(options.server, 'tcr-qs/t/tcr/web/endpoint/c/request/getOwners', form_filed)
        owner = owner.split(',')[4].split(':')[1]
        if owner:
            owners = owner[1:-1]
            if owners == 'null' or owners == 'nul':
                owners = ''
    return owners


# def TencentMain(argv, data=None):
#     """The real main function in tencent."""
#     # define global setting
#     global options
#     global username
#     parser = getParser()
#     parser.parse_args(argv[1:])
#     options, args = setInitparser(parser).parse_args(argv[1:])
#     # Set root path
#     paths = []
#     if data == None:
#         for i, item in enumerate(args):
#             args[i] = args[i].replace('\\', '/')
#             if item == '.':  # remove only .
#                 args[i] = ''
#             elif item[0] == '.' and item[1] == '/':  # remove './'
#                 args[i] = args[i][2:]
#             if item[-1] == '/':  # remove path end '/'
#                 args[i] = args[i][:-1]
#             if os.path.exists(item):  # get target path
#                 paths.append(args[i])
#                 if len(paths) > 1 and (item[0] == '/' or (len(item) > 1 and item[1] == ':')):
#                     ErrorExit("The target path must be relative path when passed Multi-Paths")
#     options.path = '.'
#     if len(paths) == 1 and paths[0] != '':
#         options.path = paths[0]
#     options.args = paths
#     # Check update
#     ValidataVersion()
#     global verbosity
#     verbosity = options.verbose
#     if verbosity >= 3:
#         logging.getLogger().setLevel(logging.DEBUG)
#     elif verbosity >= 2:
#         logging.getLogger().setLevel(logging.INFO)
#     # If get version
#     if options.version_info:
#         StatusUpdate("version:" + options.version_info)
#         StatusUpdate(
#             "See http://git.code.oa.com/code/codeheart/blob/master/tcr%20script/TCRPY-README.md for more details")
#         sys.exit(0)
#     # Check user
#     if not options.email:
#         os.environ.setdefault('USER', '')
#         os.environ.setdefault('USERNAME', '')
#         options.email = os.environ['USER'] or os.environ['USERNAME']
#         # if options.email and options.email != 'root':
#         #  print "You do not specify an username, we set the default value as: ", options.email
#     username = options.email or raw_input("User(outlook account):").strip()
#     if not username:
#         ErrorExit("A non-empty -e User is required")
#     username = TencentFormatAccount(username)
#     # If send comment
#     if options.comments:
#         CommnetSender(options).SendComment()
#         sys.exit(0)
#     # Else send request
#     vcs = GuessVCS(options)
#     if isinstance(vcs, SubversionVCS):
#         # Guessing the base field is only supported for Subversion.
#         # Note: Fetching base files may become deprecated in future releases.
#         guessed_base = vcs.GuessBase(True)
#     else:
#         ErrorExit("The script is support svn only.")
#     global base
#     base = guessed_base
#     isSshPath = False
#     if base.startswith('svn+ssh'):
#         isSshPath = True
#         base = FormatSvnUrl(base)
#     toName = options.reviewers
#     if options.server[-1] == '/':
#         options.server = options.server[:-1]  # kill last '/'
#     message = options.message
#     if not message and not options.issue:
#         message = raw_input("New request subject: ").strip()
#         if not message:
#             ErrorExit("A non-empty message is required")
#     description = options.description
#     if options.description_file:
#         if description:
#             ErrorExit("Can't specify description and description_file")
#         f = open(options.description_file, 'r')
#         description = f.read()
#         f.close()
#     """
#     if options.encoding:
#        options.encoding = options.encoding.lower()
#        if options.encoding not in ENCODING_ALL:
#           ErrorExit("only support: %s" % str(ENCODING_ALL))
#     """
#     ccName = TencentFormatAccount(options.cc)
#     # validate username
#     usernames = username
#     if toName:
#         usernames = ";".join([usernames, toName])
#     # if ccName :
#     #  usernames = ";".join([usernames,ccName])
#     form_validata = [("usernames", usernames)]
#     # form_validata.append(("isclient", "true"))
#     # validata = OpenHttp(options.server, "websvn/ldap.jsp",form_validata).strip()
#     validata = OpenHttp(options.server, "tcr-qs/t/rc-biz/c/client/checkPythonClientUsernames",
#                         form_validata).strip().replace('"', '')
#     if validata:
#         ErrorExit(""" user: "%s" are not exist.""" % (validata))
#     # ForceLdapAuth(options.server, username)
#     if data is None:
#         data = vcs.GenerateDiff(args)
#     try:
#         data = handleCharSet(data)
#     except UnicodeDecodeError, e:
#         logging.info('auto convert src error: \n' + data, e)
#         logging.info('you can use svn diff to check the file info')
#     if not options.sponsorfilelist:
#         data = vcs.PostProcessDiff(data)
#         files = vcs.GetBaseFilesName(data)
#         data, curfiles = FilterData(data, files)
#         appendData = CheckCopyFile(curfiles)
#         if appendData != '':
#             if data[-1] != '\r' and data[-1] != '\n':
#                 data = data + "\r\n" + appendData
#             else:
#                 data += appendData
#     if not options.issue:
#         # owners = GetCodeOwners(svnurls)
#         owners = GetCodeOwners(base)
#         if (owners != '') and (owners[0] != '"') and (owners[-1] != '"'):
#             owners = ';'.join(owners.split(';;;'))
#             agreeyes = raw_input(
#                 "The reviewers have already contained the following code owners:\n  " + owners + "\nContinue? y(es)").strip().lower()
#             # toName = owners
#             if agreeyes != '' and agreeyes != 'y' and agreeyes != 'ye' and agreeyes != 'yes':
#                 ErrorExit("Request be canceled.")
#     # toName = TencentFormatAccount(toName)
#     else:
#         owners = ''
#     if owners != '':
#         owners = TencentFormatAccount(owners)
#     if not toName and not options.issue:
#         if owners != '':
#             toName = raw_input("Input reviewers:" + owners).strip()
#         else:
#             toName = raw_input("Input reviewers:").strip()
#         if owners != '':
#             if toName.endswith(';'):
#                 toName += owners[0:-1]
#             else:
#                 toName += (';' + owners[0:-1])
#         if not toName:
#             ErrorExit("A non-empty -r REVIEWERS is required")
#     form_upload = [("username", username), ("author", username), ("comment", "upload from tcr client " + REAL_VERSION),
#                    ("isclient", "true")]
#     if len(data) > MAX_UPLOAD_SIZE:
#         ErrorExit('svn diff file is too large')
#     elif len(data) == 0:
#         ErrorExit('svn diff file is empty')
#     else:
#         if options.sponsorfilelist:
#             uploaded_diff_file = [("data", "client_upload_" + REAL_VERSION_ANOTHER + "_%s.st" % username, data)]
#         else:
#             uploaded_diff_file = [("data", "client_upload_" + REAL_VERSION_ANOTHER + "_%s.diff" % username, data)]
#     ctype, body = EncodeMultipartFormData(form_upload, uploaded_diff_file)
#     StatusUpdate("Uploading diff files...")
#     response_body = OpenHttp(options.server, "tcr-qs/t/request/u/UploadCodeFilesController", form_upload, body,
#                              content_type=ctype)
#     fileId = int(response_body)
#     if not fileId:
#         ErrorExit('upload diff file failed!')
#         # elif not options.issue:
#         # StatusUpdate('upload diff file successful.')
#     form_request = [("codeFileId", fileId)]
#     if message:
#         form_request.append(("name", TryEncode(message + " ")))
#     form_request.append(("requestType", 15))
#     base = urllib.unquote(base).decode('utf8')
#     form_request.append(("rootUrl", base))
#     # form_request.append(("charset", options.encoding if options.encoding else "UTF-8"))
#     form_request.append(("toName", toName))
#     if ccName:
#         form_request.append(("ccName", ccName))
#     if not description:
#         description = ""
#     pathTips = " from http path"
#     if isSshPath:
#         pathTips = " from ssh path"
#     form_request.append(("notes", TryEncode(description + " (created by tcr.py " + REAL_VERSION + pathTips + ")")))
#     form_request.append(("remark", TryEncode(description + " (created by tcr.py " + REAL_VERSION + pathTips + ")")))
#     form_request.append(("username", username))
#     form_request.append(("charset", "UTF-8"))
#     form_request.append(("creatorName", username))
#     form_request.append(("isclient", "true"))
#     form_request.append(DEFAULT_NEEDED_PARAMETERS)
#     if options.multi_pass:
#         form_request.append(("flowTypeAfterPassing", 80002L))
#     actionUrl = "tcr-qs/t/tcr/web/endpoint/c/request/addRequestFromPythonClient"
#     if options.sponsorfilelist:
#         actionUrl = "tcr-qs/t/tcr/web/endpoint/c/request/addStatusFileRequestFromPythonClient"
#     if options.issue:
#         form_request.append(("requestId", int(options.issue)))
#         actionUrl = "tcr-qs/t/tcr/web/endpoint/c/request/uploadRequestPatchSetFromPythonClient"
#     # ErrorExit('mannual exit.')
#     # print urllib.unquote(urllib.urlencode(form_request)).decode('utf8')
#     diffRequest = GetRequest(options.server, actionUrl, form_request)
#     # diffRequest.add_header('cookie', ldapCookie)
#     try:
#         ropen = urllib2.urlopen(diffRequest)
#         responseRequest = ropen.read()
#         ropen.close()
#         responseDict = eval(responseRequest)
#         result = responseDict['successfully'].decode('utf-8')
#         if result == 'true':
#             responseId = int(responseDict['requestId'])
#             if not options.issue:
#                 StatusUpdate('request(id:%d) has been created successfully.' % responseId)
#             else:
#                 StatusUpdate('request(id:%d) has been updated successfully.' % responseId)
#         else:
#             responseMsg = responseDict['exceptionMessage'].decode('utf-8')
#             ErrorExit(responseMsg)
#         sys.exit(0)
#     except Exception, e:
#         ErrorExit('Server response exception by URL: %s.\r\n%s' % (actionUrl, e))


def GetBaseFilesName(diff):
    """
    Helper that calls GetBase file for each file in the patch.
    Returns:
        A dictionary that maps from filename to GetBaseFile's tuple.  Filenames are retrieved based on lines that start with "Index:" or "Property changes on:".
    """
    files = {}
    for line in diff.splitlines(True):
        if line.startswith('Index:') or line.startswith('Property changes on:'):
            unused, filename = line.split(':', 1)
            # On Windows if a file has property changes its filename uses '\'
            # instead of '/'.
            filename = filename.strip().replace('\\', '/')
            # files[filename] = self.GetBaseFile(filename)
            files[filename] = ""
    return files


def TencentMain(argv, svn_address, revision, proj_key):
    """The real main function in tencent."""
    # define global setting
    global options
    global username
    parser = getParser()
    parser.parse_args(argv[1:])
    options, args = setInitparser(parser).parse_args(argv[1:])
    # Set root path
    # paths = []
    # if data == None:
    #     for i, item in enumerate(args):
    #         args[i] = args[i].replace('\\', '/')
    #         if item == '.':  # remove only .
    #             args[i] = ''
    #         elif item[0] == '.' and item[1] == '/':  # remove './'
    #             args[i] = args[i][2:]
    #         if item[-1] == '/':  # remove path end '/'
    #             args[i] = args[i][:-1]
    #         if os.path.exists(item):  # get target path
    #             paths.append(args[i])
    #             if len(paths) > 1 and (item[0] == '/' or (len(item) > 1 and item[1] == ':')):
    #                 ErrorExit("The target path must be relative path when passed Multi-Paths")
    options.path = '.'

    logger.info(options)
    # if len(paths) == 1 and paths[0] != '':
    #     options.path = paths[0]
    # options.args = paths
    # Check update
    ValidataVersion()
    # Check user
    if not options.email:
        os.environ.setdefault('USER', '')
        os.environ.setdefault('USERNAME', '')
        options.email = os.environ['USER'] or os.environ['USERNAME']
        # if options.email and options.email != 'root':
        #  print "You do not specify an username, we set the default value as: ", options.email
    username = options.email or input("User(outlook account):").strip()
    if not username:
        ErrorExit("A non-empty -e User is required")
    username = TencentFormatAccount(username)
    # If send comment
    if options.comments:
        CommnetSender(options).SendComment()
        return
    # Else send request
    # vcs = SubversionVCS(options)  # GuessVCS(options)
    # if isinstance(vcs, SubversionVCS):
    #     # Guessing the base field is only supported for Subversion.
    #     # Note: Fetching base files may become deprecated in future releases.
    #     guessed_base = vcs.GuessBase(True)
    # else:
    #     ErrorExit("The script is support svn only.")
    # global base
    base = svn_address
    isSshPath = False
    if base.startswith('svn+ssh'):
        isSshPath = True
        base = FormatSvnUrl(base)
    toName = options.reviewers
    if options.server[-1] == '/':
        options.server = options.server[:-1]  # kill last '/'
    message = options.message
    if not message and not options.issue:
        message = input("New request subject: ").strip()
        if not message:
            ErrorExit("A non-empty message is required")
    description = options.description
    if options.description_file:
        if description:
            ErrorExit("Can't specify description and description_file")
        f = open(options.description_file, 'r')
        description = f.read()
        f.close()
    """
    if options.encoding:
       options.encoding = options.encoding.lower()
       if options.encoding not in ENCODING_ALL:
          ErrorExit("only support: %s" % str(ENCODING_ALL))
    """
    ccName = TencentFormatAccount(options.cc)
    # validate username
    usernames = username
    if toName:
        usernames = ";".join([usernames, toName])
    # if ccName :
    #  usernames = ";".join([usernames,ccName])
    form_validata = [("usernames", usernames)]
    # form_validata.append(("isclient", "true"))
    # validata = OpenHttp(options.server, "websvn/ldap.jsp",form_validata).strip()
    validata = OpenHttp(options.server, "tcr-qs/t/rc-biz/c/client/checkPythonClientUsernames", form_validata).strip().replace('"', '')
    if validata:
        logger.info("tcr valid username: {}".format(validata))
        # _usernames = usernames.split(";")
        if ccName:
            _ccName = ccName.split(",")
            for _username in validata.split(";"):
                if _username in _ccName:
                    _ccName.remove(_username)

            if _ccName:
                ccName = ",".join(_ccName)
            else:
                ErrorExit(""" user: "{}" are not exist.""".format(validata))

        if toName:
            _toName = toName.split(",")
            for _username in validata.split(";"):
                if _username in _toName:
                    _toName.remove(_username)
            if _toName:
                toName = ",".join(_toName)
        else:
            ErrorExit(""" user: "{}" are not exist.""".format(validata))
    # ForceLdapAuth(options.server, username)
    # if data is None:
    #     data = vcs.GenerateDiff(args)
    try:
        data = os.popen("svn diff -c {} {}".format(revision, svn_address)).read()
        data = handleCharSet(data)
    except UnicodeDecodeError as e:
        logger.error('auto convert src error: \n{}, {}'.format(revision, svn_address))
        logger.error('you can use svn diff to check the file info')
        traceback.print_exc(e)
        return
    if not options.sponsorfilelist:
        # data = vcs.PostProcessDiff(data)
        files = GetBaseFilesName(data)  # vcs.GetBaseFilesName(data)
        data, curfiles = FilterData(data, files)
        appendData = CheckCopyFile(curfiles)
        if appendData != '':
            if data[-1] != '\r' and data[-1] != '\n':
                data = data + "\r\n" + appendData
            else:
                data += appendData
    if not options.issue:
        # owners = GetCodeOwners(svnurls)
        owners = GetCodeOwners(base)
        if (owners != '') and (owners[0] != '"') and (owners[-1] != '"'):
            owners = ';'.join(owners.split(';;;'))
            agreeyes = input(
                "The reviewers have already contained the following code owners:\n  " + owners + "\nContinue? y(es)").strip().lower()
            # toName = owners
            if agreeyes != '' and agreeyes != 'y' and agreeyes != 'ye' and agreeyes != 'yes':
                ErrorExit("Request be canceled.")
    # toName = TencentFormatAccount(toName)
    else:
        owners = ''
    if owners != '':
        owners = TencentFormatAccount(owners)
    form_upload = [("username", username), ("author", username), ("comment", "upload from tcr client " + REAL_VERSION), ("isclient", "true")]
    if len(data) > MAX_UPLOAD_SIZE:
        #   提取对比的所有文件名
        diff_files: List[str] = re.findall(r'Index:\s*(.+)',data)
        file_names = list(map(lambda item: os.path.basename(item.strip()), diff_files))
        return ErrorExit('svn diff file is too large, {}'.format(','.join(file_names)))
    elif len(data) == 0:
        return ErrorExit('svn diff file is empty')
    else:
        if options.sponsorfilelist:
            uploaded_diff_file = [("data", "client_upload_" + REAL_VERSION_ANOTHER + "_%s.st" % username, data)]
        else:
            uploaded_diff_file = [("data", "client_upload_" + REAL_VERSION_ANOTHER + "_%s.diff" % username, data)]
    ctype, body = EncodeMultipartFormData(form_upload, uploaded_diff_file)
    StatusUpdate("Uploading diff files...")
    response_body = OpenHttp(options.server, "tcr-qs/t/request/u/UploadCodeFilesController", form_upload, body.encode('utf-8'), content_type=ctype)

    fileId = int(response_body)
    if not fileId:
        ErrorExit('upload diff file failed!')
        # elif not options.issue:
        # StatusUpdate('upload diff file successful.')
    form_request = [("codeFileId", fileId)]
    if message:
        form_request.append(("name", message + " "))
    form_request.append(("requestType", 15))
    base = urllib.parse.unquote(base)
    form_request.append(("rootUrl", base))
    # form_request.append(("charset", options.encoding if options.encoding else "UTF-8"))
    form_request.append(("toName", toName))
    if ccName:
        form_request.append(("ccName", ccName))
    if not description:
        description = ""
    pathTips = " from http path"
    if isSshPath:
        pathTips = " from ssh path"
    form_request.append(("notes", description + " (created by tcr.py " + REAL_VERSION + pathTips + ")"))
    form_request.append(("remark", description + " (created by tcr.py " + REAL_VERSION + pathTips + ")"))
    form_request.append(("username", username))
    form_request.append(("charset", "UTF-8"))
    form_request.append(("creatorName", username))
    form_request.append(("isclient", "true"))
    form_request.append(DEFAULT_NEEDED_PARAMETERS)
    if options.multi_pass:
        form_request.append(("flowTypeAfterPassing", 80002))
    actionUrl = "tcr-qs/t/tcr/web/endpoint/c/request/addRequestFromPythonClient"
    if options.sponsorfilelist:
        actionUrl = "tcr-qs/t/tcr/web/endpoint/c/request/addStatusFileRequestFromPythonClient"
    if options.issue:
        form_request.append(("requestId", int(options.issue)))
        actionUrl = "tcr-qs/t/tcr/web/endpoint/c/request/uploadRequestPatchSetFromPythonClient"
    # ErrorExit('mannual exit.')
    # print urllib.unquote(urllib.urlencode(form_request)).decode('utf8')
    diffRequest = GetRequest(options.server, actionUrl, form_request)
    # diffRequest.add_header('cookie', ldapCookie)
    try:
        ropen = urllib.request.urlopen(diffRequest)
        responseRequest = ropen.read()
        ropen.close()
        responseDict = eval(responseRequest)
        result = responseDict['successfully']
        if result == 'true':
            responseId = int(responseDict['requestId'])
            TCR.objects.update_or_create(id=responseId, key=proj_key)
            if not options.issue:
                StatusUpdate('request(id:%d) has been created successfully.' % responseId)
            else:
                StatusUpdate('request(id:%d) has been updated successfully.' % responseId)
        else:
            responseMsg = responseDict['exceptionMessage']
            ErrorExit(responseMsg)
        return
    except Exception as e:
        ErrorExit('Server response exception by URL: %s.\r\n%s' % (actionUrl, e))


def main(argv, svn_address, revision, proj_key):
    logger.info(f"argv: {argv}, svn_address: {svn_address}, revision: {revision}, proj_key: {proj_key}")
    try:
        if os.name == 'posix':
            os.environ['LC_ALL'] = 'en_US.UTF-8'
        TencentMain(argv, svn_address, revision, proj_key)
    except KeyboardInterrupt:
        ErrorExit("Interrupted.")


if __name__ == "__main__":
    main(sys.argv[:7], *sys.argv[7:])
