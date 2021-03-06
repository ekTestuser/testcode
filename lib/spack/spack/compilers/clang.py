##############################################################################
# Copyright (c) 2013-2016, Lawrence Livermore National Security, LLC.
# Produced at the Lawrence Livermore National Laboratory.
#
# This file is part of Spack.
# Created by Todd Gamblin, tgamblin@llnl.gov, All rights reserved.
# LLNL-CODE-647188
#
# For details, see https://github.com/llnl/spack
# Please also see the LICENSE file for our notice and the LGPL.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License (as
# published by the Free Software Foundation) version 2.1, February 1999.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the IMPLIED WARRANTY OF
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the terms and
# conditions of the GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
##############################################################################
import re
import os
import sys
import spack
import spack.compiler as cpr
from spack.compiler import *
from spack.util.executable import *
import llnl.util.tty as tty
from spack.version import ver
from shutil import copytree, ignore_patterns


class Clang(Compiler):
    # Subclasses use possible names of C compiler
    cc_names = ['clang']

    # Subclasses use possible names of C++ compiler
    cxx_names = ['clang++']

    # Subclasses use possible names of Fortran 77 compiler
    f77_names = ['gfortran']

    # Subclasses use possible names of Fortran 90 compiler
    fc_names = ['gfortran']

    # Named wrapper links within spack.build_env_path
    link_paths = {'cc': 'clang/clang',
                  'cxx': 'clang/clang++',
                  # Use default wrappers for fortran, in case provided in
                  # compilers.yaml
                  'f77': 'clang/gfortran',
                  'fc': 'clang/gfortran'}

    @property
    def is_apple(self):
        ver_string = str(self.version)
        return ver_string.endswith('-apple')

    @property
    def openmp_flag(self):
        if self.is_apple:
            tty.die("Clang from Apple does not support Openmp yet.")
        else:
            return "-fopenmp"

    @property
    def cxx11_flag(self):
        if self.is_apple:
            # FIXME: figure out from which version Apple's clang supports c++11
            return "-std=c++11"
        else:
            if self.version < ver('3.3'):
                tty.die("Only Clang 3.3 and above support c++11.")
            else:
                return "-std=c++11"

    @classmethod
    def default_version(cls, comp):
        """The '--version' option works for clang compilers.
        On most platforms, output looks like this::

            clang version 3.1 (trunk 149096)
            Target: x86_64-unknown-linux-gnu
            Thread model: posix

        On Mac OS X, it looks like this::

            Apple LLVM version 7.0.2 (clang-700.1.81)
            Target: x86_64-apple-darwin15.2.0
            Thread model: posix
        """
        if comp not in cpr._version_cache:
            compiler = Executable(comp)
            output = compiler('--version', output=str, error=str)

            ver = 'unknown'
            match = re.search(r'^Apple LLVM version ([^ )]+)', output)
            if match:
                # Apple's LLVM compiler has its own versions, so suffix them.
                ver = match.group(1) + '-apple'
            else:
                # Normal clang compiler versions are left as-is
                match = re.search(r'clang version ([^ )]+)', output)
                if match:
                    ver = match.group(1)

            cpr._version_cache[comp] = ver

        return cpr._version_cache[comp]

    def _find_full_path(self, path):
        basename = os.path.basename(path)

        if not self.is_apple or basename not in ('clang', 'clang++'):
            return super(Clang, self)._find_full_path(path)

        xcrun = Executable('xcrun')
        full_path = xcrun('-f', basename, output=str)
        return full_path.strip()

    @classmethod
    def fc_version(cls, fc):
        version = get_compiler_version(
            fc, '-dumpversion',
            # older gfortran versions don't have simple dumpversion output.
            r'(?:GNU Fortran \(GCC\))?(\d+\.\d+(?:\.\d+)?)')
        # This is horribly ad hoc, we need to map from gcc/gfortran version
        # to clang version, but there could be multiple clang
        # versions that work for a single gcc/gfortran version
        if sys.platform == 'darwin':
            clangversionfromgcc = {'6.2.0': '8.0.0-apple'}
        else:
            clangversionfromgcc = {}
        if version in clangversionfromgcc:
            return clangversionfromgcc[version]
        else:
            return 'unknown'

    @classmethod
    def f77_version(cls, f77):
        return cls.fc_version(f77)

    def setup_custom_environment(self, env):
        """Set the DEVELOPER_DIR environment for the Xcode toolchain.

        On macOS, not all buildsystems support querying CC and CXX for the
        compilers to use and instead query the Xcode toolchain for what
        compiler to run. This side-steps the spack wrappers. In order to inject
        spack into this setup, we need to copy (a subset of) Xcode.app and
        replace the compiler executables with symlinks to the spack wrapper.
        Currently, the stage is used to store the Xcode.app copies. We then set
        the 'DEVELOPER_DIR' environment variables to cause the xcrun and
        related tools to use this Xcode.app.
        """
        super(Clang, self).setup_custom_environment(env)

        if not self.is_apple:
            return

        xcode_select = Executable('xcode-select')
        real_root = xcode_select('--print-path', output=str).strip()
        real_root = os.path.dirname(os.path.dirname(real_root))
        developer_root = os.path.join(spack.stage_path,
                                      'xcode-select',
                                      self.name,
                                      str(self.version))
        xcode_link = os.path.join(developer_root, 'Xcode.app')

        if not os.path.exists(developer_root):
            tty.warn('Copying Xcode from %s to %s in order to add spack '
                     'wrappers to it. Please do not interrupt.'
                     % (real_root, developer_root))

            # We need to make a new Xcode.app instance, but with symlinks to
            # the spack wrappers for the compilers it ships. This is necessary
            # because some projects insist on just asking xcrun and related
            # tools where the compiler runs. These tools are very hard to trick
            # as they do realpath and end up ignoring the symlinks in a
            # "softer" tree of nothing but symlinks in the right places.
            copytree(real_root, developer_root, symlinks=True,
                     ignore=ignore_patterns('AppleTV*.platform',
                                            'Watch*.platform',
                                            'iPhone*.platform',
                                            'Documentation',
                                            'swift*'))

            real_dirs = [
                'Toolchains/XcodeDefault.xctoolchain/usr/bin',
                'usr/bin',
            ]

            bins = ['c++', 'c89', 'c99', 'cc', 'clang', 'clang++', 'cpp']

            for real_dir in real_dirs:
                dev_dir = os.path.join(developer_root,
                                       'Contents',
                                       'Developer',
                                       real_dir)
                for fname in os.listdir(dev_dir):
                    if fname in bins:
                        os.unlink(os.path.join(dev_dir, fname))
                        os.symlink(os.path.join(spack.build_env_path, 'cc'),
                                   os.path.join(dev_dir, fname))

            os.symlink(developer_root, xcode_link)

        env.set('DEVELOPER_DIR', xcode_link)
