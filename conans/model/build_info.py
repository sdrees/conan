import os
from collections import OrderedDict
from copy import copy

from conans.errors import ConanException
from conans.util.conan_v2_mode import conan_v2_behavior

DEFAULT_INCLUDE = "include"
DEFAULT_LIB = "lib"
DEFAULT_BIN = "bin"
DEFAULT_RES = "res"
DEFAULT_SHARE = "share"
DEFAULT_BUILD = ""
DEFAULT_FRAMEWORK = "Frameworks"

COMPONENT_SCOPE = "::"


class DefaultOrderedDict(OrderedDict):

    def __init__(self, factory):
        self.factory = factory
        super(DefaultOrderedDict, self).__init__()

    def __getitem__(self, key):
        if key not in self.keys():
            super(DefaultOrderedDict, self).__setitem__(key, self.factory())
            super(DefaultOrderedDict, self).__getitem__(key).name = key
        return super(DefaultOrderedDict, self).__getitem__(key)

    def __copy__(self):
        the_copy = DefaultOrderedDict(self.factory)
        for key, value in super(DefaultOrderedDict, self).items():
            the_copy[key] = value
        return the_copy


class _CppInfo(object):
    """ Object that stores all the necessary information to build in C/C++.
    It is intended to be system independent, translation to
    specific systems will be produced from this info
    """
    def __init__(self):
        self.name = None
        self.names = {}
        self.system_libs = []  # Ordered list of system libraries
        self.includedirs = []  # Ordered list of include paths
        self.srcdirs = []  # Ordered list of source paths
        self.libdirs = []  # Directories to find libraries
        self.resdirs = []  # Directories to find resources, data, etc
        self.bindirs = []  # Directories to find executables and shared libs
        self.builddirs = []
        self.frameworks = []  # Macos .framework
        self.frameworkdirs = []
        self.rootpaths = []
        self.libs = []  # The libs to link against
        self.defines = []  # preprocessor definitions
        self.cflags = []  # pure C flags
        self.cxxflags = []  # C++ compilation flags
        self.sharedlinkflags = []  # linker flags
        self.exelinkflags = []  # linker flags
        self.build_modules = []
        self.rootpath = ""
        self.sysroot = ""
        self._build_modules_paths = None
        self._include_paths = None
        self._lib_paths = None
        self._bin_paths = None
        self._build_paths = None
        self._res_paths = None
        self._src_paths = None
        self._framework_paths = None
        self.version = None  # Version of the conan package
        self.description = None  # Description of the conan package
        # When package is editable, filter_empty=False, so empty dirs are maintained
        self.filter_empty = True

    def _filter_paths(self, paths):
        abs_paths = [os.path.join(self.rootpath, p)
                     if not os.path.isabs(p) else p for p in paths]
        if self.filter_empty:
            return [p for p in abs_paths if os.path.isdir(p)]
        else:
            return abs_paths

    @property
    def build_modules_paths(self):
        if self._build_modules_paths is None:
            self._build_modules_paths = [os.path.join(self.rootpath, p) if not os.path.isabs(p)
                                         else p for p in self.build_modules]
        return self._build_modules_paths

    @property
    def include_paths(self):
        if self._include_paths is None:
            self._include_paths = self._filter_paths(self.includedirs)
        return self._include_paths

    @property
    def lib_paths(self):
        if self._lib_paths is None:
            self._lib_paths = self._filter_paths(self.libdirs)
        return self._lib_paths

    @property
    def src_paths(self):
        if self._src_paths is None:
            self._src_paths = self._filter_paths(self.srcdirs)
        return self._src_paths

    @property
    def bin_paths(self):
        if self._bin_paths is None:
            self._bin_paths = self._filter_paths(self.bindirs)
        return self._bin_paths

    @property
    def build_paths(self):
        if self._build_paths is None:
            self._build_paths = self._filter_paths(self.builddirs)
        return self._build_paths

    @property
    def res_paths(self):
        if self._res_paths is None:
            self._res_paths = self._filter_paths(self.resdirs)
        return self._res_paths

    @property
    def framework_paths(self):
        if self._framework_paths is None:
            self._framework_paths = self._filter_paths(self.frameworkdirs)
        return self._framework_paths

    def get_name(self, generator):
        return self.names.get(generator, self.name)

    # Compatibility for 'cppflags' (old style property to allow decoration)
    def get_cppflags(self):
        conan_v2_behavior("'cpp_info.cppflags' is deprecated, use 'cxxflags' instead")
        return self.cxxflags

    def set_cppflags(self, value):
        conan_v2_behavior("'cpp_info.cppflags' is deprecated, use 'cxxflags' instead")
        self.cxxflags = value

    cppflags = property(get_cppflags, set_cppflags)


class Component(_CppInfo):

    def __init__(self, rootpath):
        super(Component, self).__init__()
        self.rootpath = rootpath
        self.includedirs.append(DEFAULT_INCLUDE)
        self.libdirs.append(DEFAULT_LIB)
        self.bindirs.append(DEFAULT_BIN)
        self.resdirs.append(DEFAULT_RES)
        self.builddirs.append(DEFAULT_BUILD)
        self.frameworkdirs.append(DEFAULT_FRAMEWORK)
        self.requires = []


class CppInfo(_CppInfo):
    """ Build Information declared to be used by the CONSUMERS of a
    conans. That means that consumers must use this flags and configs i order
    to build properly.
    Defined in user CONANFILE, directories are relative at user definition time
    """
    def __init__(self, root_folder):
        super(CppInfo, self).__init__()
        self.rootpath = root_folder  # the full path of the package in which the conans is found
        self.includedirs.append(DEFAULT_INCLUDE)
        self.libdirs.append(DEFAULT_LIB)
        self.bindirs.append(DEFAULT_BIN)
        self.resdirs.append(DEFAULT_RES)
        self.builddirs.append(DEFAULT_BUILD)
        self.frameworkdirs.append(DEFAULT_FRAMEWORK)
        self.components = DefaultOrderedDict(lambda: Component(self.rootpath))
        # public_deps is needed to accumulate list of deps for cmake targets
        self.public_deps = []
        self.configs = {}

    def __getattr__(self, config):
        def _get_cpp_info():
            result = _CppInfo()
            result.rootpath = self.rootpath
            result.sysroot = self.sysroot
            result.includedirs.append(DEFAULT_INCLUDE)
            result.libdirs.append(DEFAULT_LIB)
            result.bindirs.append(DEFAULT_BIN)
            result.resdirs.append(DEFAULT_RES)
            result.builddirs.append(DEFAULT_BUILD)
            result.frameworkdirs.append(DEFAULT_FRAMEWORK)
            return result

        return self.configs.setdefault(config, _get_cpp_info())

    def _raise_incorrect_components_definition(self, package_name, package_requires):
        # Raise if mixing components
        if (self.includedirs != [DEFAULT_INCLUDE] or
                self.libdirs != [DEFAULT_LIB] or
                self.bindirs != [DEFAULT_BIN] or
                self.resdirs != [DEFAULT_RES] or
                self.builddirs != [DEFAULT_BUILD] or
                self.frameworkdirs != [DEFAULT_FRAMEWORK] or
                self.libs or
                self.system_libs or
                self.frameworks or
                self.defines or
                self.cflags or
                self.cxxflags or
                self.sharedlinkflags or
                self.exelinkflags or
                self.build_modules) and self.components:
            raise ConanException("self.cpp_info.components cannot be used with self.cpp_info "
                                 "global values at the same time")
        if self.configs and self.components:
            raise ConanException("self.cpp_info.components cannot be used with self.cpp_info configs"
                                 " (release/debug/...) at the same time")

        # Raise on component name
        for comp_name, comp in self.components.items():
            if comp_name == package_name:
                raise ConanException("Component name cannot be the same as the package name: '%s'"
                                     % comp_name)

        if self.components:
            comp_requires = set()
            for comp_name, comp in self.components.items():
                for comp_require in comp.requires:
                    if COMPONENT_SCOPE in comp_require:
                        comp_requires.add(
                            comp_require[:comp_require.find(COMPONENT_SCOPE)])
            pkg_requires = [require.ref.name for require in package_requires.values()]
            # Raise on components requires without package requires
            for pkg_require in pkg_requires:
                if pkg_require not in comp_requires:
                    raise ConanException("Package require '%s' not used in components requires"
                                         % pkg_require)
            # Raise on components requires requiring inexistent package requires
            for comp_require in comp_requires:
                if comp_require not in pkg_requires:
                    raise ConanException("Package require '%s' declared in components requires "
                                         "but not defined as a recipe requirement" % comp_require)


class _BaseDepsCppInfo(_CppInfo):
    def __init__(self):
        super(_BaseDepsCppInfo, self).__init__()

    def update(self, dep_cpp_info):

        def merge_lists(seq1, seq2):
            return [s for s in seq1 if s not in seq2] + seq2

        self.system_libs = merge_lists(self.system_libs, dep_cpp_info.system_libs)
        self.includedirs = merge_lists(self.includedirs, dep_cpp_info.include_paths)
        self.srcdirs = merge_lists(self.srcdirs, dep_cpp_info.src_paths)
        self.libdirs = merge_lists(self.libdirs, dep_cpp_info.lib_paths)
        self.bindirs = merge_lists(self.bindirs, dep_cpp_info.bin_paths)
        self.resdirs = merge_lists(self.resdirs, dep_cpp_info.res_paths)
        self.builddirs = merge_lists(self.builddirs, dep_cpp_info.build_paths)
        self.frameworkdirs = merge_lists(self.frameworkdirs, dep_cpp_info.framework_paths)
        self.libs = merge_lists(self.libs, dep_cpp_info.libs)
        self.frameworks = merge_lists(self.frameworks, dep_cpp_info.frameworks)
        self.build_modules = merge_lists(self.build_modules, dep_cpp_info.build_modules_paths)
        self.rootpaths.append(dep_cpp_info.rootpath)

        # Note these are in reverse order
        self.defines = merge_lists(dep_cpp_info.defines, self.defines)
        self.cxxflags = merge_lists(dep_cpp_info.cxxflags, self.cxxflags)
        self.cflags = merge_lists(dep_cpp_info.cflags, self.cflags)
        self.sharedlinkflags = merge_lists(dep_cpp_info.sharedlinkflags, self.sharedlinkflags)
        self.exelinkflags = merge_lists(dep_cpp_info.exelinkflags, self.exelinkflags)

        if not self.sysroot:
            self.sysroot = dep_cpp_info.sysroot

    @property
    def build_modules_paths(self):
        return self.build_modules

    @property
    def include_paths(self):
        return self.includedirs

    @property
    def lib_paths(self):
        return self.libdirs

    @property
    def src_paths(self):
        return self.srcdirs

    @property
    def bin_paths(self):
        return self.bindirs

    @property
    def build_paths(self):
        return self.builddirs

    @property
    def res_paths(self):
        return self.resdirs

    @property
    def framework_paths(self):
        return self.frameworkdirs


class DepCppInfo(object):

    def __init__(self, cpp_info):
        self._cpp_info = cpp_info
        self._libs = None
        self._system_libs = None
        self._frameworks = None
        self._defines = None
        self._cxxflags = None
        self._cflags = None
        self._sharedlinkflags = None
        self._exelinkflags = None

        self._include_paths = None
        self._lib_paths = None
        self._bin_paths = None
        self._build_paths = None
        self._res_paths = None
        self._src_paths = None
        self._framework_paths = None
        self._build_module_paths = None
        self._sorted_components = None
        self._check_component_requires()

    def __getattr__(self, item):
        try:
            attr = self._cpp_info.__getattribute__(item)
        except AttributeError:  # item is not defined, get config (CppInfo)
            attr = self._cpp_info.__getattr__(item)
        return attr

    @staticmethod
    def _merge_lists(seq1, seq2):
        return seq1 + [s for s in seq2 if s not in seq1]

    def _aggregated_values(self, item):
        values = getattr(self, "_%s" % item)
        if values is not None:
            return values
        values = getattr(self._cpp_info, item)
        if self._cpp_info.components:
            for component in self._get_sorted_components().values():
                values = self._merge_lists(values, getattr(component, item))
        setattr(self, "_%s" % item, values)
        return values

    def _aggregated_paths(self, item):
        paths = getattr(self, "_%s_paths" % item)
        if paths is not None:
            return paths
        paths = getattr(self._cpp_info, "%s_paths" % item)
        if self._cpp_info.components:
            for component in self._get_sorted_components().values():
                paths = self._merge_lists(paths, getattr(component, "%s_paths" % item))
        setattr(self, "_%s_paths" % item, paths)
        return paths

    @staticmethod
    def _filter_component_requires(requires):
        return [r for r in requires if COMPONENT_SCOPE not in r]

    def _check_component_requires(self):
        for comp_name, comp in self._cpp_info.components.items():
            if not all([require in self._cpp_info.components for require in
                        self._filter_component_requires(comp.requires)]):
                raise ConanException("Component '%s' declares a missing dependency" % comp_name)
            bad_requires = [r for r in comp.requires if r.startswith(COMPONENT_SCOPE)]
            if bad_requires:
                msg = "Leading character '%s' not allowed in %s requires: %s. Omit it to require " \
                      "components inside the same package." \
                      % (COMPONENT_SCOPE, comp_name, bad_requires)
                raise ConanException(msg)

    def _get_sorted_components(self):
        """
        Sort Components from most dependent one first to the less dependent one last
        :return: List of sorted components
        """
        if not self._sorted_components:
            if any([[require for require in self._filter_component_requires(comp.requires)]
                    for comp in self._cpp_info.components.values()]):
                ordered = OrderedDict()
                components = copy(self._cpp_info.components)
                while len(ordered) != len(self._cpp_info.components):
                    # Search next element to be processed
                    for comp_name, comp in components.items():
                        # Check if component is not required and can be added to ordered
                        if comp_name not in [require for dep in components.values() for require in
                                             self._filter_component_requires(dep.requires)]:
                            ordered[comp_name] = comp
                            del components[comp_name]
                            break
                    else:
                        raise ConanException("There is a dependency loop in "
                                             "'self.cpp_info.components' requires")
                self._sorted_components = ordered
            else:  # If components do not have requirements, keep them in the same order
                self._sorted_components = self._cpp_info.components
        return self._sorted_components

    @property
    def build_modules_paths(self):
        return self._aggregated_paths("build_modules")

    @property
    def include_paths(self):
        return self._aggregated_paths("include")

    @property
    def lib_paths(self):
        return self._aggregated_paths("lib")

    @property
    def src_paths(self):
        return self._aggregated_paths("src")

    @property
    def bin_paths(self):
        return self._aggregated_paths("bin")

    @property
    def build_paths(self):
        return self._aggregated_paths("build")

    @property
    def res_paths(self):
        return self._aggregated_paths("res")

    @property
    def framework_paths(self):
        return self._aggregated_paths("framework")

    @property
    def libs(self):
        return self._aggregated_values("libs")

    @property
    def system_libs(self):
        return self._aggregated_values("system_libs")

    @property
    def frameworks(self):
        return self._aggregated_values("frameworks")

    @property
    def defines(self):
        return self._aggregated_values("defines")

    @property
    def cxxflags(self):
        return self._aggregated_values("cxxflags")

    @property
    def cflags(self):
        return self._aggregated_values("cflags")

    @property
    def sharedlinkflags(self):
        return self._aggregated_values("sharedlinkflags")

    @property
    def exelinkflags(self):
        return self._aggregated_values("exelinkflags")


class DepsCppInfo(_BaseDepsCppInfo):
    """ Build Information necessary to build a given conans. It contains the
    flags, directories and options if its dependencies. The conans CONANFILE
    should use these flags to pass them to the underlaying build system (Cmake, make),
    so deps info is managed
    """

    def __init__(self):
        super(DepsCppInfo, self).__init__()
        self._dependencies = OrderedDict()
        self.configs = {}

    def __getattr__(self, config):
        return self.configs.setdefault(config, _BaseDepsCppInfo())

    @property
    def dependencies(self):
        return self._dependencies.items()

    @property
    def deps(self):
        return self._dependencies.keys()

    def __getitem__(self, item):
        return self._dependencies[item]

    def update(self, cpp_info, pkg_name):
        assert isinstance(cpp_info, (CppInfo, DepCppInfo))
        self._dependencies[pkg_name] = cpp_info
        super(DepsCppInfo, self).update(cpp_info)
        for config, cpp_info in cpp_info.configs.items():
            self.configs.setdefault(config, _BaseDepsCppInfo()).update(cpp_info)
