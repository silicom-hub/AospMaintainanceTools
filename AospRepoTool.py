#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
Copyright © 2021, Silicom Region Ouest
Author: Bertrand Virfollet <bvirfollet@silicom.fr>

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the “Software”), to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions
of the Software.

The Software is provided “as is”, without warranty of any kind, express or implied, including but not limited
to the warranties of merchantability, fitness for a particular purpose and noninfringement. In no event shall
the authors or copyright holders be liable for any claim, damages or other liability, whether in an action
of contract, tort or otherwise, arising from, out of or in connection with the software or the use or other
dealings in the Software.

Except as contained in this notice, the name of the Silicom shall not be used in advertising or
otherwise to promote the sale, use or other dealings in this Software without prior written authorization from
 the Silicom.
"""

import xmltodict
import subprocess
import pdb
import os.path
import git
import json
import tarfile
import logging
import stat

from argparse import ArgumentParser
from os.path import join, exists, abspath, expanduser, isdir, isfile, islink
from os import makedirs, walk


class AospProject:
    def __init__(self, basename, path, git_repo, remote, revision, options, logger):
        self._extracted = False
        self._forcedPatch = None
        self._basename = basename
        self._path = path
        self._args = options
        self.logger = logger
        self._git_repo = git_repo
        self._commit_courant = None
        self._commit_manifest = None
        self._commit_sincetag = None
        self._commit_totag = None
        self._commit_co = None
        self._revision = revision
        self._remote = remote

        # Retrieve the remote url
        self._remote_url = ""
        if self._git_repo.remotes:
            self._remote_url = list(self._git_repo.remotes[0].urls)[0]
        else:
            self.logger.warning("No remote registered in {} ?!".format(self._path))

    def __repr__(self):
        return self._path

    @property
    def path(self):
        return self._path

    @property
    def revision(self):
        return self._revision

    @property
    def remote_url(self):
        return self._remote_url

    @property
    def basename(self):
        return self._basename

    @property
    def commit_manifest(self):
        return self._commit_manifest

    @property
    def s_commit_manifest(self):
        ret = ""
        if self._commit_manifest:
            ret = self._commit_manifest.hexsha[:9]
        return ret

    @property
    def commit_courant(self):
        return self._commit_courant

    @property
    def s_commit_courant(self):
        ret = ""
        if self._commit_courant:
            ret = self._commit_courant.hexsha[:9]
        return ret

    @property
    def commit_sincetag(self):
        return self._commit_sincetag

    @property
    def s_commit_sincetag(self):
        ret = ""
        if self._commit_sincetag:
            ret = self._commit_sincetag.hexsha[:9]
        return ret

    @property
    def commit_totag(self):
        return self._commit_totag

    @property
    def s_commit_totag(self):
        ret = ""
        if self._commit_totag:
            ret = self._commit_totag.hexsha[:9]
        return ret

    @property
    def commit_co(self):
        return self._commit_co

    @property
    def s_commit_co(self):
        ret = ""
        if self._commit_co:
            ret = self._commit_co.hexsha[:9]
        return ret

    def unshallow(self):
        """
        This method process the unshallow querry on this folder
        :param path: Absolute path of git repository to unshallow
        :return:
        """
        try:
            self.logger.info("Unshallowing project")
            subprocess.check_output(
                "cd {}/{} && git fetch --unshallow".format(self._args['aosp'], self._path),
                shell=True)
        except Exception as e:
            self.logger.error("Impossible to unshallow {}: {}".format(self._path, e))

    def getPatch(self, commit_src, commit_dst, file=''):
        """
        Retrieve patch content
        :param commit_src: Starting commit id for patch generation
        :param commit_dst: Ending commit id for patch generation
        :param file: Optionnal file name to use as reference for patch production
        :return: patch is of type 'bytes', convert before use
        """
        if file:
            patch = subprocess.check_output(
                "cd {}/{} && git format-patch -k -s --full-index --stdout --binary"
                " {}..{} -- {} ".format(self._args['aosp'], self._path, commit_src, commit_dst, file),
                shell=True)
        else:
            patch = subprocess.check_output(
                "cd {}/{} && git format-patch -k -s --full-index --stdout --binary"
                " {}..{}".format(self._args['aosp'], self._path, commit_src, commit_dst),
                shell=True)
        return patch

    def savePatch(self, commit_src, commit_dst, output_folder, patch_filename, file=''):
        """
        Store Patch content on file system (git outputs correctly utf-8 badly formatted character
        conversion contrary to getPatch method)
        :param commit_src: Starting commit id for patch generation
        :param commit_dst: Ending commit id for patch generation
        :param output_folder: absolute path where patch will be stored (created if needed)
        :param patch_filename: patch file name
        :param file: Optionnal file name to use as reference for patch production
        :return:
        """
        # Creates output folder if needed
        os.makedirs(output_folder, exist_ok=True)

        # Creates patch directly in output folder
        if file:
            p = subprocess.Popen(
                "cd {}/{} && git format-patch -k -s --full-index"
                " --binary --stdout {}..{} -- {} > {}".format(self._args['aosp'], self._path,
                                                              commit_src, commit_dst,
                                                              file,
                                                              join(output_folder, patch_filename)),
                shell=True)
        else:
            p = subprocess.Popen(
                "cd {}/{} && git format-patch -k -s --full-index"
                " --binary {}..{} --stdout > {}".format(self._args['aosp'], self.path,
                                                        commit_src, commit_dst,
                                                        join(output_folder, patch_filename)),
                shell=True)
        p.wait()

    def needPatch(self, setNeedPatch=None):
        """
        This method evaluates if this project needs to produce a patch file
        :return:
        """
        if setNeedPatch is not None:
            self._forcedPatch = setNeedPatch
        else:
            if self._forcedPatch:
                return self._forcedPatc

            if self._path == "kernel/msm-4.14":
                a = 1

            # No op if already done
            self.extractCommits()

            needPatch = False
            if self._commit_courant and self._commit_co and (self._commit_courant != self._commit_co):
                needPatch = True
        return needPatch

    def isValid(self):
        """
        Fetch interesting commits if needed and return if this project is in a valid state
        :return:
        """
        res = True
        if not self._extracted:
            self.extractCommits()

        # Check for filtered out reasons
        if self._args['since_tag'] and self._commit_sincetag is None:
            # Skip this project
            self.logger.warning("! Impossible to retrieve {} in {}".format(self._args['since_tag'], self._path))
            res = False

        if self._args['to_tag'] and self._commit_totag is None:
            # Skip this project
            self.logger.warning("! Impossible to retrieve {} in {}".format(self._args['to_tag'], self._path))
            res = False
        return res

    def exitIfCritical(self):
        """
        Check critical exit condition and exits if needed
        :return:
        """
        if not self._extracted:
            self.extractCommits()

        # Check for error case
        if self._commit_manifest is None:
            # Seems that this AOSP project is out of control => exit
            self.logger.error("! Impossible to locate manifest revision {} in {}".format(self._revision, self._path))
            exit(1)

    def setCommitCo(self, commit):
        """
        Storing reference commit for patch generation
        :param commit: Commit Id selected
        :return:
        """
        self._commit_co = commit

    def isDirty(self):
        """
        This method check for exit conditions and exits if needed
        :return: None
        """
        # Check for uncommited or untracked files
        is_dirty = False
        if self._git_repo.is_dirty(untracked_files=not self._args['ignore_untrack']):
            is_dirty = True
            if not self._args['inspect_repo']:
                if self._args['ignore_symlink']:
                    is_dirty = False
                    for f in self._git_repo.untracked_files:
                        if not islink(join(self._args['aosp'], self._path, f)):
                            is_dirty = True
                            break
                if is_dirty and not self._args['ignore_dirty']:
                    self.logger.warning("! {} n'est pas propre => exit".format(self._path))
                    exit(-1)
            else:
                if self._args['ignore_symlink']:
                    is_dirty = False
                    for f in self._git_repo.untracked_files:
                        if not islink(join(self._args['aosp'], self._path, f)):
                            is_dirty = True
                            break
                if is_dirty:
                    self.logger.warning("! {} n'est pas propre".format(self._path))
                else:
                    self.logger.info("!  Symlink found in {}".format(self._path))
        return is_dirty

    def checkout(self, commit):
        if self.isDirty():
            for f in self._git_repo.untracked_files:
                os.unlink(join(self._args['aosp'], self._path, f))
        self._git_repo.checkout(commit)

    def fetchTags(self):
        """
        This method feeds all available tags from git repo
        :param path: Full path to the git repo
        :return: void
        """
        try:
            self.logger.debug("Fetching tags")
            # Let's fetch
            subprocess.check_output(
                "cd {}/{} && git fetch -j {} --tags".format(self._args['aosp'], self._path, self._args['jobs']),
                shell=True)
        except Exception as e:
            self.logger.error("Error while fetching tags in {}: {}".format(self._path, e))
            exit(1)

    def extractCommits(self):
        """
        This method extract commit ids related to since/to tags and sets commit id which should be considered for
         later processing
        :return:
        """
        if not self._extracted:
            # Retrieve HEAD commit
            self._commit_courant = self._git_repo.head.commit

            # Force use of fully qualified branch name in order to prevent local homonyme branch
            for prefix in [self._remote + '/', 'm/', self._remote + 'm/', 'refs/tags/', 'refs/heads/', '']:
                try:
                    self._commit_manifest = self._git_repo.commit(prefix + self._revision)
                    self.logger.debug("+ {} manifest revision  {} ({})".format(self._path, prefix + self._revision,
                                                                               self.s_commit_manifest))
                    break
                except:
                    pass

            since_tag = self._args['since_tag']
            to_tag = self._args['to_tag']

            # Ensure corresponding tags are fetched
            if since_tag or to_tag:
                self.fetchTags()

            if since_tag:
                try:
                    self._commit_sincetag = self._git_repo.commit('refs/tags/' + since_tag)
                    self.logger.debug("+ {} \'since tag\' found {} ({})".format(self._path, since_tag,
                                                                                self.s_commit_sincetag))
                except:
                    pass

            if to_tag:
                try:
                    self._commit_totag = self._git_repo.commit('refs/tags/' + to_tag)
                    self.logger.debug("+ {} to tag found revision  {} ({})".format(self._path, to_tag,
                                                                                   self.s_commit_totag))
                    if self._commit_totag != self._commit_courant:
                        self.logger.info("Target tag is not current commit?!")
                        self._commit_courant = self._commit_totag
                except:
                    self.logger.debug("! Impossible to retrieve to_tag {} in {}".format(to_tag, self._path))

            # Consider the manifest is pointing to sincetag if available
            if self._commit_sincetag:
                self._commit_manifest = self._commit_sincetag

            # Record extraction has been done
            self._extracted = True

    def searchAncestors(self, manager):
        """
        This method analyse history to find the commit on which patch should be produced and record in
        manager if project should be considered as tracked
        :param manager: AospRepoTool object
        :return:
        """
        list_commits_manifest = []

        # No ops if already done
        self.extractCommits()

        # Use commit_totag as current commit if not already existing
        if self.commit_totag is None:
            self._commit_totag = self._commit_courant

        # Handle case where current commit is older as manifest one
        try:
            list_commits_manifest = list(self._git_repo.iter_commits(self._commit_manifest))
        except Exception as e:
            self.logger.error(
                "Impossible to find initial commit!! {} in {}".format(self.s_commit_manifest, self._path))
            while True:
                resp = input("Continue? (O/N)").lower()
                if resp in ['n', 'o', 'y']:
                    break
            if resp != 'n':
                return
            else:
                # Exits on critical situation
                self.logger.error("=> Exit")
                exit(-1)

        # Search in history if the current commit is found
        if self._commit_courant in list_commits_manifest:
            # If the current point is before manifest revision
            if self._commit_courant != list_commits_manifest[0]:
                self.logger.warning("! Use of an older version {} {}"
                                    " -> {}".format(self._path, self.s_commit_manifest, self.s_commit_courant))
            # Add to tracked project list in order to add unshallow instructions
            manager.addTrackRemote(self._path)
            # Store that patcher script should co on this early point of time
            self._commit_co = self._commit_courant
        else:
            # Search for a history divergence point and use it as starting point for patch production and patcher
            # script checkout instructions
            list_commits_head = list(self._git_repo.iter_commits(self._commit_courant))
            if self._commit_manifest not in list_commits_head:
                self._commit_co = None
                # Divergence found
                commit_ancetre_commun = None
                for commit in list_commits_manifest:
                    if commit in list_commits_head:
                        # Common ancestor is found.
                        commit_ancetre_commun = commit
                        break
                # Complete history divergence, use the oldest commit if opt in
                if not commit_ancetre_commun:
                    self.logger.error(
                        "! Attention: impossible de trouver un ancètre commun dans les "
                        "historiques de {}?!".format(self._path))
                    if self._args['oldest_commit']:
                        commit_ancetre_commun = list_commits_manifest[-1]
                    else:
                        self.logger.error("Ignoring patches from {}".format(self._path))
                        # Record no need to patch
                        self.needPatch(False)
                        return

                # Recording where to checkout
                self._commit_co = commit_ancetre_commun
                self.logger.warning("! Delivery diverged from manifest "
                                    "{} ancest|{} -> manif|{}/curent|{}".format(self._path, self.s_commit_co,
                                                                                self.s_commit_manifest,
                                                                                self.s_commit_courant))
                # Add to unshallowable projects in genetated patcher script
                manager.addTrackRemote(self._path)

    def process(self, manager):
        """
        This method successively retrieve tags and commit of interests,
        determines if patch production is needed, and output patchs in the right format
        :param manager:
        :return:
        """
        # Check dirtiness
        is_dirty = self.isDirty()
        if is_dirty and not self._args['ignore_dirty']:
            self.logger.warning("! {} is not clean => exit".format(self._path))
            exit(-1)

        # Filter out projects without interesting modifications
        if (self._args['to_tag'] and self._commit_totag and self._commit_manifest and
                self._commit_totag == self._commit_manifest):
            self.logger.debug("! No modification of interest in {}".format(self._path))
            self.setCommitCo(self._commit_totag)
            manager.addPatch((self, None, False))
            return

        # Keep project matching tracking key word
        if self._args['track_remote']:
            for tr in self._args['track_remote']:
                if tr in self._remote_url:
                    manager.addTrackRemote(self.path)
                    if self._args['to_tag'] and self._commit_totag != self._commit_manifest:
                        # Check if delivery tag is above reference branch (manifest revision)
                        list_commits_head = list(self._git_repo.iter_commits(self._commit_manifest))
                        if self._commit_totag in list_commits_head:
                            # Manifest points on newer commit than to_tag, keep to_tag as original checkout point as
                            # it must be added in patching script
                            self.setCommitCo(self._commit_totag)
                            manager.addPatch((self, None, False))
                            return None
                        else:
                            # Manifest points on older commit than to_tag, keep manifest as original checkout and
                            # process patch to to_tag
                            self.logger.warning("! Modifications in tracked repo {} ?".format(self._path))
                            self.setCommitCo(self._commit_manifest)
                            break

        if self.needPatch():
            # Extract patches and keep reference for later generation of patching script
            self.processPatchs(manager)

    def processPatchs(self, manager):
        """
        This method computes starting point in history based on the different options and produces a
        file patch if needed
        :param manager: AospRepoTool parent object
        :return:
        """
        need_patch = False
        patch = None

        # Extraction is no ops if already done
        self.extractCommits()

        # Look for initial reference commit for patch generation
        self.searchAncestors(manager)

        if not self.needPatch():
            self.logger.debug("No need to patch {} : DONE".format(self._path))
            return

        output_path = self._args['output_folder']

        # Creation of patch files if needed and add it to manager patch list if needed
        self.logger.info("Production of patchs for {}".format(self._path))

        if self._args['diff_format']:
            list_commits = list(self._git_repo.iter_commits("{}..{}".format(self.s_commit_co, self.s_commit_courant)))
            list_commits.append(self.s_commit_co)
            list_commits.reverse()

            # Create a patch file per commit id
            # TODO check if there is merge commits and handle it properly
            for idx, commit in enumerate(list_commits):
                if idx + 1 >= len(list_commits):
                    break
                try:
                    patch = self.getPatch(list_commits[idx], list_commits[idx + 1])
                except Exception as e:
                    self.logger.error('Erreur de production du patch dans {}: \n{}'.format(self._path, str(e)))
                    exit(1)
                if patch:
                    try:
                        dest_path = join(output_path, self._path.replace(self._args['aosp'], ''))
                        file_name = '{:02d}_{}.patch'.format(idx, self._path.replace('/', '_'))
                        self.savePatch(list_commits[idx], list_commits[idx + 1], dest_path, file_name)
                        manager.addPatch((self, file_name, True))
                    except Exception as e:
                        self.logger.error("Impossible to retrieve patch in {}: \n{}".format(self._path, e))
                        exit(-1)
        else:
            try:
                # Single patch file
                patch = self.getPatch(self.s_commit_co, self.s_commit_courant)
            except Exception as e:
                self.logger.error('Error while producing patch in {}: \n{}'.format(self._path, str(e)))
                exit(1)
            finally:
                self._git_repo.head.commit = self._commit_courant

            if patch:
                filename = '{}.patch'.format(self._path.replace('/', '_'))
                self.savePatch(self.s_commit_co, self.s_commit_courant, output_path, filename)
                manager.addPatch((self, filename, True))
        self.logger.info("Production of patchs for {} : DONE".format(self._path))


class AospRepoTool:
    def __init__(self, **kwargs):
        self.logger = None
        self._args = {}
        if kwargs:
            self._args == kwargs

        if self._args.get("logger", None) is not None:
            self.logger = self._args["logger"]

        self._parser = None
        self._list_manifests = []
        self._list_projects = []
        self._list_removed_projects = []
        self._list_patch = []
        self._list_remaining_git_folders = []
        self._list_archives = []
        self._list_track_remote = []
        self._list_oem_projects = []

        self._default_revision = None
        self._default_remote = None

    @property
    def args(self):
        return self._args

    @property
    def projects(self):
        return self._list_projects

    def setPath(self, aosp):
        if not exists(aosp):
            raise Exception("No such path {}".format(aosp))
        self._args['aosp'] = aosp

    def setLogger(self, logger):
        self.logger = logger

    def addTrackRemote(self, path):
        if path:
            self._list_track_remote.append(path)

    def addPatch(self, entry=None):
        if entry:
            Found = None
            for stored_entry in self._list_patch:
                if stored_entry[0] == entry[0]:
                    Found = stored_entry
                    break
            if Found is None:
                self._list_patch.append(entry)
            else:
                self.logger.error("#### Duplicate entry {} vs stored {} ####".format(entry, stored_entry))

    def updateRemainingGitFolders(self, path=""):
        """
        Utilitary method to handle a check list for non tracked project at global scope
        :param path: Path of the project
        :return: None, exits if needed
        """
        if path in self._list_remaining_git_folders:
            self._list_remaining_git_folders.remove(path)
            self.logger.debug("Removing {} from unhandled git projects "
                              "({} left)".format(path, len(self._list_remaining_git_folders)))

    def selectRevision(self, projet_xml=None):
        """
        This method reads and select active revision for this xml project entry
        :param projet_xml: dico to the project descriptor
        :return: string with revision name
        """
        if projet_xml is None:
            raise Exception("Parameters are invalid")

        # Use global, default revision or project revision according to project entry
        proj_revision = ""
        if projet_xml and '@revision' in projet_xml:
            proj_revision = projet_xml['@revision']
            if "oem_code" in proj_revision:
                self._list_oem_projects.append(self._path)

        if not proj_revision:
            proj_revision = self._default_revision

        # Stripping of 'refs/tags/' and 'refs/heads' in full project spec.
        if proj_revision:
            for header in ["refs/tags/", "refs/heads/", "refs/"]:
                if header in proj_revision:
                    proj_revision = proj_revision[len(header):]
                    break
        return proj_revision

    def initArgParser(self):
        """
        This method initialises the argument parser for this tool
        :return:
        """
        description = """AospRepoTool.py is a tool for producing AOSP patch delivery from an original 'repo' source tree
in complete or différential format. Example:
./AospRepoTool.py -a .../aosp_top_dir -o .../delivery_folder <Options>
Run \'./AospRepoTool.py -h\' for more information"""
        self._parser = ArgumentParser(description=description)
        self._parser.add_argument('-a', '--aosp', help="Path to top dir of AOSP source tree",
                                  dest="aosp", default='.')
        self._parser.add_argument('-d', '--debug', help="Activates debug traces",
                                  dest='debug', action="store_true", default=False)
        self._parser.add_argument("-f", "--fetch", help="Fetching tags before processing",
                                  dest='fetch', action="store_true", default=False)
        self._parser.add_argument("-df", "--diff_format", help="Production of patchs in subfolders organised similarily "
                                                               "to original source tree, one patch per commit",
                                  dest='diff_format', action="store_true", default=False)
        self._parser.add_argument("-i", "--inspect_repo", help="Dry run",
                                  dest="inspect_repo", action="store_true", default=False)
        self._parser.add_argument("-id", "--ignore_dirty", help="Ignores untracked and checked in files in projects",
                                  dest="ignore_dirty", action="store_true", default=False)
        self._parser.add_argument("-is", "--ignore_symlink", help="Ignore symlinks in source tree",
                                  dest="ignore_symlink", action="store_true", default=False)
        self._parser.add_argument("-iu", "--ignore_untrack", help="Ignore untracked content in projects",
                                  dest="ignore_untrack", action="store_true", default=False)
        self._parser.add_argument("-j", "--jobs", help="Number of CPU to dedicate for multitasking",
                                  dest="jobs", default=4)
        self._parser.add_argument("-m", "--manifests", help="Specific path for \'.repo' folder",
                                  dest="manifests", default=None)
        self._parser.add_argument("-nr", "--no_rebase", help="Inhibits rebasing instruction generation in patch script",
                                  dest="no_rebase", action="store_true", default=False)
        self._parser.add_argument("-s", "--scope_projects", help="Explicit list of project to handle in delivery. "
                                                                 "Keep empty for full processing",
                                  dest="scope_projects", nargs='+', default=[])
        self._parser.add_argument("-sp", "--skip_projects", help="List of project's name to filter out from delivery.",
                                  dest="skip_projects", nargs='+', default=[])
        self._parser.add_argument("-st", "--since_tag", help="Start patch production since alternative tags instead of"
                                                             " manifest revision if found",
                                  dest="since_tag", default="")
        self._parser.add_argument("-tt", "--to_tag", help="Stop patch production to a specific tag if found",
                                  dest="to_tag", default=None)
        self._parser.add_argument("-o", "--output_folder", help="Path to folder in which outputing patchs, and generated"
                                                                " scripts",
                                  dest="output_folder", default='./delivery')
        self._parser.add_argument("-oc", "--oldest_commit", help="In case of split history from manifest, use the oldest"
                                                                 " commit in history",
                                  dest="oldest_commit", action="store_true", default=False)
        self._parser.add_argument("-p", "--product", help="Name of terminal",                                 dest="product", default="product")
        self._parser.add_argument("-pt", "--product_tag", help="Delivery tag",
                                  dest="product_tag", default="XX_XY_V1.0")
        self._parser.add_argument("-q", "--quiet", help="Silent execution",
                                  dest="quiet", action="store_true", default=False)
        self._parser.add_argument("-t", "--tar", help="Produce tar.gz of modified projects",
                                  dest="tar", action="store_true", default=False,)
        self._parser.add_argument("-tr", "--track_remote", help="Output all git repos which use this remote name for "
                                                                "fetching",
                                  dest="track_remote", nargs='+', default=[])
        self._parser.add_argument("-u", "--unshallow", help="Add unshalloing instruction in generated script if needed",
                                  dest="unshallow", action="store_true", default=False)
        self._args = vars(self._parser.parse_args())

    def processArgs(self):
        """
        This methods make validity checks and normalisation (path expansion, existence check and autocompletion) of
        provided arguments.
        :return: Normalized arguments
        """
        self._args['aosp'] = expanduser(self._args['aosp'])

        if self._args['aosp'] == '.':
            self._args['aosp'] = abspath('.')

        if self._args['manifests'] is None:
            self._args['manifests'] = os.path.join(self._args['aosp'], '.repo')
        else:
            self._args['manifests'] = expanduser(self._args['manifests'])
            if self._args['manifests'] == '.':
                self._args['manifests'] = abspath('.')

        self._args['output_folder'] = expanduser(self._args['output_folder'])
        if self._args['output_folder'] == '.':
            self._args['output_folder'] = abspath('.')

        if not exists(self._args['aosp']) or not exists(self._args['manifests']) or not self._args['output_folder']:
            self._parser.print_usage()
            exit(1)

        if not isdir(self._args['aosp']):
            self.logger.error("Check your AOSP path: {}".format(self._args['aosp']))
            self._parser.print_usage()
            exit(2)

        if not exists(self._args['output_folder']):
            makedirs(self._args['output_folder'])

    def parseManifests(self):
        """
        This method reads and stores usefull manifest in the indicated manifest folder
        :return: void
        """
        # Build a list of manifests to handle
        if isfile(self._args['manifests']):
            # The only manifest to handle is the one indicated in argument
            self._list_manifests = [self._args['manifests']]
        else:
            for root, dirs, files in walk(self._args['manifests']):
                for f_name in files:
                    if '.xml' in f_name:
                        if not islink(f_name):
                            # Add this xml manifest for later handling
                            logger.info("+ Adding file {} to the processing xml to handle".format(f_name))
                            self._list_manifests.append(root + '/' + f_name)
                        else:
                            logger.debug("! {} is symlink => Ignored".format(f_name))

        # Build a list of folder under git management
        for root, dirs, files in walk(self._args['aosp']):
            if '.git' in root:
                continue
            if '.repo' in root:
                continue
            if '.git' in dirs:
                # Adding parent folder in the list of git repositories
                self._list_remaining_git_folders.append(root.replace(self._args['aosp'] + '/', ''))
        logger.debug("Full list of git projects:\n{}".format(len(self._list_remaining_git_folders)))

    def processManifests(self):
        """
        Simple method to process all manifest file as provided by program arguments
        :return:
        """
        for manifest in self._list_manifests:
            self.processManifest(manifest)

    def processManifest(self, manifest):
        """
        Analysis of project indicated by manifests and produces a patch when current commit is not the one indicated
        by manifest revision
        :param manifest: Manifest to handle
        :return:
        """
        basename = manifest.split('/')[-1].split('.')[0]
        xml_manifest = None
        self.logger.debug("\nSearch for default remote in {}".format(manifest))
        with open(manifest, 'r') as xml_input:
            xml = xml_input.read()
            xml_manifest = xmltodict.parse(xml)

        revision = None
        remote = None
        remote_revision = None

        if 'manifest' in xml_manifest:
            remote_name = self._default_remote
            default_revision = self._default_revision

            # Retrieve default revision this manifest
            if 'default' in xml_manifest['manifest']:
                self._default_revision = xml_manifest['manifest']['default']['@revision']

                self._default_remote = xml_manifest['manifest']['default']['@remote']

            # Retrieve default remote for this manifest
            if 'remote' in xml_manifest['manifest']:
                if isinstance(xml_manifest['manifest']['remote'], list):
                    remote = xml_manifest['manifest']['remote'][0]
                    remote_name = remote['@name']
                    self.logger.warning(
                        "! Several remote exists for this manifest!! => Selection of {}".format(remote))
                    pdb.set_trace()
                else:
                    remote = xml_manifest['manifest']['remote']
                    remote_name = remote['@name']
                    if '@revision' in remote:
                        remote_revision = remote['@revision']

            if remote_revision:
                default_revision = remote_revision

            # If there are real modifications
            if 'project' in xml_manifest['manifest']:
                if not isinstance(xml_manifest['manifest']['project'], list):
                    xml_manifest['manifest']['project'] = [xml_manifest['manifest']['project']]
                for projet_xml in xml_manifest['manifest']['project']:
                    projet_obj = self.parseXmlProject(projet_xml, basename, default_revision, remote_name)
                    if projet_obj and projet_obj not in self._list_projects:
                        self._list_projects.append(projet_obj)

    def parseXmlProject(self, projet_xml, basename, default_revision, default_remote):
        """
        This method initialise AospProject object based on project xml description
        :param projet_xml: XML description of current project
        :param basename: xml file basename
        :param default_revision: default revision for current manifest
        :return:
        """
        # Use default config for since tag and to tag
        since_tag = self._args['since_tag']
        to_tag = self._args['to_tag']
        path = None
        remote = default_remote

        try:
            path = projet_xml['@path']
        except Exception as e:
            self.logger.error("Unable to read project description: {}".format(str(e)))

        # Update remaining git projects list
        self.updateRemainingGitFolders(path)

        # Filter out unneeded projects
        if path in self._args['skip_projects']:
            self.logger.info("! Ignoring explicitly skipped project {}".format(path))
            return None

        if self._args['scope_projects'] and path not in self._args['scope_projects']:
            self.logger.info("! Ignoring out of scope project {}".format(path))
            return None

        # Retrieve active remote for this project
        if '@remote' in projet_xml:
            remote = projet_xml['@remote']

        # Select the active revision depending on xml content
        proj_revision = self.selectRevision(projet_xml)

        # Creation of git repo object for futur queries
        try:
            git_repo = git.Repo(self._args['aosp'] + '/' + path)
        except git.exc.NoSuchPathError:
            self.logger.info("- Record project as removed {}".format(path))
            self._list_removed_projects.append(path)
            return None
        except Exception as e:
            self.logger.error("!- Impossible to handle project {}: {}".format(path, str(e)))
            exit(-1)

        project = AospProject(basename, path, git_repo, remote, proj_revision, self._args, self.logger)
        if not project.isValid():
            project.exitIfCritical()

        # Record point of checkout to manifest revision if not yet defined
        if project.commit_co is None:
            project.setCommitCo(project.commit_manifest)
        return project

    def processProjects(self):
        """
        This methods iteratively extracts projects commits of interest, determines if patch production is needed
        :return:
        """
        # On transforme le dico manifest pour utiliser le commit_id (sha1) de la référence indiquée par le
        # manifest.
        # On produit un patch pour ce projet qu'on va concaténer au fichier global pour ce manifest

        # Récupération du chemin pour faire les interrogations avec git
        for projet in self._list_projects:
            projet.process(self)

    def processDelivery(self):
        """
        This method stores in output folder the delivery content according to options
        :return:
        """
        # Copy build.rc in delivery folder if any
        if exists(join(self._args['aosp'], 'build.rc')):
            try:
                subprocess.check_output("cp {} {}".format(join(self._args['aosp'], 'build.rc'),
                                                          self._args['output_folder']),
                                        shell=True)
            except Exception as e:
                pass

        # Save json file with projects tracked
        with open(join(self._args['output_folder'], "tracked_projects.json"), 'w') as fd:
            json.dump(self._list_track_remote, fd, indent=2)

        # Production des tar.gz des projets patché si besoin
        self.generateTars()

        # Une fois le remplacement branch/sha1 fait pour chaque projet, ont recréé le fichier de patch avec les modifs
        # appliquées
        # Création du script de patch si besoin
        has_content = False
        if self._list_patch or self._list_archives or self._list_removed_projects:
            has_content = True
        if not self._args['inspect_repo'] and has_content:
            if not self._args['diff_format']:
                self.generateFullInstallPatch()
            else:
                self.generateDiffPatchInstall()
            self.generateCleanupScript()

            if self._list_oem_projects:
                self.generateCleanupScript()

    def generateCleanupScript(self):
        """
        Explicit method
        :return:
        """
        self.logger.debug("\n+: Liste des projets propriétaires {}".format(self._list_oem_projects))
        file_name = join(self._args['output_folder'], '{}_restaure.sh'.format(self._args['product']))
        with open(file_name, 'w') as f_out:
            f_out.write("#!/bin/bash\n")
            f_out.write("AOSP_BASE=$1\n")

            f_out.write("if [ $# -eq 0 ]; then\n")
            f_out.write("echo \"{}_restaure.sh aosp_root_dir\"\n".format(self._args['product']))
            f_out.write("exit\n")
            f_out.write("fi\n")

            f_out.write("#Checkout explicite sur la version de base des repos qcom\n")
            for path in list_oem_projects:
                f_out.write("echo \"Restauring {}\"\n".format(path))
                f_out.write("cd $AOSP_BASE/{} && git checkout oem_code\n".format(path))

        mode = os.stat(file_name)
        os.chmod(file_name, stat.S_IMODE(mode.st_mode) | stat.S_IEXEC)

    def generateCleanupScript(self):
        """
        Explicit method
        :return:
        """
        try:
            file_name = join(self._args['output_folder'], '{}_cleanup.sh'.format(self._args['product']))
            with open(file_name, 'w') as f_out:
                f_out.write("#!/bin/bash\n")
                f_out.write("AOSP_BASE=$1\n")

                f_out.write("if [ $# -eq 0 ]; then\n")
                f_out.write("echo \"{}_cleanup.sh aosp_root_dir\"\n".format(self._args['product']))
                f_out.write("exit\n")
                f_out.write("fi\n")

                f_out.write("#Traitement des archives non suivies dans le manifest AOSP\n")
                for path, archive in self._list_archives:
                    f_out.write("echo \"Removing {}\"\n".format(path))
                    f_out.write("rm -Rf $AOSP_BASE/{}\n".format(path))

            mode = os.stat(file_name)
            os.chmod(file_name, stat.S_IMODE(mode.st_mode) | stat.S_IEXEC)
        except Exception as e:
            self.logger.error("Impossible to generate cleanup script: {}".format(e))

    def generateFullInstallPatch(self):
        """
        Explicit method
        :return:
        """
        try:
            file_name = join(self._args['output_folder'], '{}_patch.sh'.format(self._args['product']))
            with open(file_name, 'w') as f_out:
                f_out.write("#!/bin/bash\n")
                f_out.write("PATCH_HOME=$(pwd)\n")
                f_out.write("AOSP_BASE=$1\n")

                f_out.write("if [ $# -eq 0 ]; then\n")
                f_out.write("echo \"{}_patch.sh aosp_root_dir [--remove_unused]\"\n".format(self._args['product']))
                f_out.write("exit\n")
                f_out.write("fi\n")

                # basename, remote, remote_url, path, filename, commit, need_patch in self._list_patch:
                for project, filename, need_patch in self._list_patch:
                    path = project.path
                    f_out.write("#Traitement de {} - {}\n".format(project.basename, path))
                    f_out.write("echo \"$AOSP_BASE/{}\"\n".format(path))
                    f_out.write("cd $AOSP_BASE/{}\n".format(path))
                    if self._args['unshallow'] and need_patch:
                        f_out.write("git fetch {} --unshallow -j{}\n".format(project.remote, self._args['jobs']))
                    if not self._args['no_rebase']:
                        f_out.write("git checkout {}\n".format(project.s_commit_co))
                        f_out.write("if [ $? -ne 0 ]; then\n"
                                    "  echo \"Erreur pour le repo {}: checkout impossible\"\n"
                                    "  exit 1\n"
                                    "fi\n".format(path))
                    f_out.write("git stash -u\n")
                    if need_patch:
                        f_out.write("git am -3 -k --ignore-whitespace $PATCH_HOME/{}.patch\n".format(path.replace('/',
                                                                                                                  '_')))
                        f_out.write("if [ $? -ne 0 ]; then\n"
                                    "  echo \"Erreur pour le repo {}: application du patch\"\n"
                                    "  exit 1\n"
                                    "fi\n".format(path))
                    f_out.write("git tag -fa {} -m {}\n".format(self._args['product_tag'], self._args['product_tag']))
                    f_out.write("if [ $? -ne 0 ]; then\n"
                                "  echo \"Erreur pour le repo {}: application du tag\"\n"
                                "  exit 1\n"
                                "fi\n".format(path))

                if self._list_archives:
                    f_out.write("#Traitement des archives non suivies dans le manifest AOSP\n")
                    for path, archive in self._list_archives:
                        f_out.write("#Extraction de {} dans {}\n".format(archive, path))
                        f_out.write("rm -Rf $AOSP_BASE/{}\n".format(path))
                        f_out.write("tar -xf $PATCH_HOME/{} -C $AOSP_BASE\n".format(archive))
                        f_out.write("if [ $? -ne 0 ]; then\n"
                                    "  echo \"Erreur pour l'archive {}: décompression du module\"\n"
                                    "  exit 1\n"
                                    "fi\n".format(archive))
                        f_out.write("cd $AOSP_BASE/{} && git init && git add -A && "
                                    "git commit -m \"commit initial\"\n".format(path))
                        f_out.write("if [ $? -ne 0 ]; then\n"
                                    "  echo \"Erreur pour l'archive {}: initialisation du repo git\"\n"
                                    "  exit 1\n"
                                    "fi\n".format(archive))

                if self._list_removed_projects:
                    f_out.write("#Traitement des projets non suivis du manifest AOSP\n")
                    f_out.write("if [ \"$2\" = \"--remove_unused\" ]; then\n")
                    for path in self._list_removed_projects:
                        f_out.write("  cd $AOSP_BASE && rm -Rf {}\n".format(path))
                        f_out.write("  if [ $? -ne 0 ]; then\n"
                                    "    echo \"Erreur pour le chemin {}: impossible d'effacer le dossier\"\n"
                                    "  fi\n".format(path))
                    f_out.write("fi\n")
                f_out.write("cd $PATCH_HOME\n")
            mode = os.stat(file_name)
            os.chmod(file_name, stat.S_IMODE(mode.st_mode) | stat.S_IEXEC)
        except Exception as e:
            self.logger.error("Impossible to generate patching script: {}".format(e))

    def generateDiffPatchInstall(self):
        file_name = join(self._args['output_folder'], '{}_patch.sh'.format(self._args['product']))
        with open(file_name, 'w') as f_out:
            f_out.write("#!/bin/bash\n")
            f_out.write("PATCH_HOME=$(pwd)\n")
            f_out.write("AOSP_BASE=$1\n")

            f_out.write("if [ $# -eq 0 ]; then\n")
            f_out.write("echo \"{}_patch.sh aosp_root_dir [--remove_unused]\"\n".format(self._args['product']))
            f_out.write("exit\n")
            f_out.write("fi\n")

            for project, file, need_patch in self._list_patch:
                f_out.write("echo \"$AOSP_BASE/{}\"\n".format(project.path))
                f_out.write("cd $AOSP_BASE/{}\n".format(project.path))
                f_out.write("git stash -u\n")
                if need_patch:
                    f_out.write("git am -3 -k --ignore-whitespace $PATCH_HOME/{}/{}\n".format(project.path, file))
                    f_out.write("if [ $? -ne 0 ]; then\n"
                                "  echo \"Erreur pour le repo {}: application du patch\"\n"
                                "  exit 1\n"
                                "fi\n".format(project.path))
                f_out.write("git tag -fa {} -m {}\n".format(self._args['product_tag'], self._args['product_tag']))
                f_out.write("if [ $? -ne 0 ]; then\n"
                            "  echo \"Erreur pour le repo {}: application du tag\"\n"
                            "  exit 1\n"
                            "fi\n".format(project.path))
            f_out.write("cd $PATCH_HOME\n")

            if self._list_archives:
                f_out.write("#Traitement des archives non suivies dans le manifest AOSP\n")
                for path, archive in self._list_archives:
                    f_out.write("#Extraction de {} dans {}\n".format(archive, path))
                    f_out.write("rm -Rf $AOSP_BASE/{}\n".format(path))
                    f_out.write("tar -xf $PATCH_HOME/{} -C $AOSP_BASE\n".format(archive))
                    f_out.write("if [ $? -ne 0 ]; then\n"
                                "  echo \"Erreur pour l'archive {}: décompression du module\"\n"
                                "  exit 1\n"
                                "fi\n".format(archive))
                    f_out.write("cd $AOSP_BASE/{} && git init && git add -A && "
                                "git commit -m \"commit initial\"\n".format(path))
                    f_out.write("if [ $? -ne 0 ]; then\n"
                                "  echo \"Erreur pour l'archive {}: initialisation du repo git\"\n"
                                "  exit 1\n"
                                "fi\n".format(archive))

        mode = os.stat(file_name)
        os.chmod(file_name, stat.S_IMODE(mode.st_mode) | stat.S_IEXEC)

    def generateTars(self):
        if not self._args['inspect_repo'] and self._args['tar'] and self._list_patch:
            # Creation of zip file for this project
            # for basename, remote, remote_url, path, s_commit_co, need_patch in self._list_patch:
            for project, _, need_patch in self._list_patch:
                arch_name = project.path.replace('/', '_') + ".tar.gz"
                self.logger.warning("Production d'un tar.gz pour {}".format(arch_name))
                if not exists(join(self._args['output_folder'], 'archive')):
                    makedirs(join(self._args['output_folder'], 'archive'))
                if not exists(join(self._args['output_folder'], 'archive', arch_name)):
                    with tarfile.open(join(self._args['output_folder'], 'archive', arch_name), mode='w:gz') as tar:
                        def archive_filter(tarinfo):
                            if '.git' in tarinfo.name:
                                return None
                            else:
                                tarinfo.name = tarinfo.name.replace(self._args['aosp'][1:] + '/', '')
                                self.logger.debug("T+: Adding {} to archive {}".format(tarinfo.name, arch_name))
                            return tarinfo
                        tar.add(join(self._args['aosp'], project.path), filter=archive_filter)

        # Records git project not tracked by manifest system
        if self._list_remaining_git_folders:
            self.logger.warning(
                "Few projects have not been handles by manifests:\n {}".format(self._list_remaining_git_folders))
            with open(join(self._args['output_folder'], 'left_repos.json'), 'w') as f_out:
                json.dump(self._list_remaining_git_folders, f_out, indent=4)

            if not self._args['inspect_repo']:
                # Creation of tar.gz file pour those projects
                for path in self._list_remaining_git_folders:
                    arch_name = path.replace('/', '_') + ".tar.gz"
                    if not exists(arch_name):
                        with tarfile.open(join(self._args['output_folder'], arch_name), mode='w:gz') as tar:
                            def archive_filter(tarinfo):
                                if '.git' in tarinfo.name:
                                    return None
                                else:
                                    tarinfo.name = tarinfo.name.replace(self._args['aosp'][1:] + '/', '')
                                # self.logger.debug("T+: Adding {} to archive {}".format(tarinfo.name, arch_name))
                                return tarinfo

                            tar.add(join(self._args['aosp'], path), filter=archive_filter)
                    self._list_archives.append((path, arch_name))


if __name__ == '__main__':
    tool = AospRepoTool()

    # Setup options and parameters
    tool.initArgParser()
    args = tool.args
    level = logging.WARNING
    if not args['quiet']:
        if args['debug']:
            level = logging.DEBUG
        else:
            level = logging.INFO

    logging.basicConfig(level=level)
    logger = logging.getLogger(name="AospRepoTool.py")
    logger_git = logging.getLogger(name="git.cmd")
    logger_git.setLevel(level=logging.INFO)

    tool.setLogger(logger)

    # Argument normalisation
    tool.processArgs()

    # Manifests parsing
    tool.parseManifests()

    # Projects processing
    tool.processManifests()

    # Projects processing
    tool.processProjects()

    # Patch Script generation
    tool.processDelivery()
