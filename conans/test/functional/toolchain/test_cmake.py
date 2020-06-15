# coding=utf-8

import os
import platform
import textwrap
import unittest

from nose.plugins.attrib import attr
from parameterized.parameterized import parameterized

from conans.model.ref import ConanFileReference, PackageReference
from conans.test.utils.tools import TestClient


@attr("toolchain")
class Base(unittest.TestCase):

    conanfile = textwrap.dedent("""
        from conans import ConanFile, CMake, CMakeToolchain

        class App(ConanFile):
            settings = "os", "arch", "compiler", "build_type"
            requires = "hello/0.1"
            generators = "cmake_find_package_multi"
            options = {"shared": [True, False], "fPIC": [True, False]}
            default_options = {"shared": False, "fPIC": True}

            def toolchain(self):
                tc = CMakeToolchain(self)
                tc.definitions["DEFINITIONS_BOTH"] = True
                tc.definitions.debug["DEFINITIONS_CONFIG"] = "Debug"
                tc.definitions.release["DEFINITIONS_CONFIG"] = "Release"
                return tc

            def build(self):
                cmake = CMake(self)
                cmake.configure()
                cmake.build()
        """)

    lib_h = textwrap.dedent("""
        #pragma once
        #ifdef WIN32
          #define APP_LIB_EXPORT __declspec(dllexport)
        #else
          #define APP_LIB_EXPORT
        #endif
        APP_LIB_EXPORT void app();
        """)

    lib_cpp = textwrap.dedent("""
        #include <iostream>
        #include "app.h"
        #include "hello.h"

        void app() {
            std::cout << "Hello: " << HELLO_MSG <<std::endl;
            #ifdef NDEBUG
            std::cout << "App: Release!" <<std::endl;
            #else
            std::cout << "App: Debug!" <<std::endl;
            #endif
            std::cout << "DEFINITIONS_BOTH: " << DEFINITIONS_BOTH << "\\n";
            std::cout << "DEFINITIONS_CONFIG: " << DEFINITIONS_CONFIG << "\\n";
        }
        """)

    app = textwrap.dedent("""
        #include "app.h"

        int main() {
            app();
        }
        """)

    cmakelist = textwrap.dedent("""
        cmake_minimum_required(VERSION 2.8)
        project(App C CXX)

        if(CONAN_TOOLCHAIN_INCLUDED AND CMAKE_VERSION VERSION_LESS "3.15")
            include("${CMAKE_BINARY_DIR}/conan_project_include.cmake")
        endif()

        if(NOT CMAKE_TOOLCHAIN_FILE)
            message(FATAL ">> Not using toolchain")
        endif()

        message(">> CMAKE_GENERATOR_PLATFORM: ${CMAKE_GENERATOR_PLATFORM}")
        message(">> CMAKE_BUILD_TYPE: ${CMAKE_BUILD_TYPE}")
        message(">> CMAKE_CXX_FLAGS: ${CMAKE_CXX_FLAGS}")
        message(">> CMAKE_CXX_FLAGS_DEBUG: ${CMAKE_CXX_FLAGS_DEBUG}")
        message(">> CMAKE_CXX_FLAGS_RELEASE: ${CMAKE_CXX_FLAGS_RELEASE}")
        message(">> CMAKE_C_FLAGS: ${CMAKE_C_FLAGS}")
        message(">> CMAKE_C_FLAGS_DEBUG: ${CMAKE_C_FLAGS_DEBUG}")
        message(">> CMAKE_C_FLAGS_RELEASE: ${CMAKE_C_FLAGS_RELEASE}")
        message(">> CMAKE_SHARED_LINKER_FLAGS: ${CMAKE_SHARED_LINKER_FLAGS}")
        message(">> CMAKE_EXE_LINKER_FLAGS: ${CMAKE_EXE_LINKER_FLAGS}")

        message(">> CMAKE_CXX_STANDARD: ${CMAKE_CXX_STANDARD}")
        message(">> CMAKE_CXX_EXTENSIONS: ${CMAKE_CXX_EXTENSIONS}")

        message(">> CMAKE_POSITION_INDEPENDENT_CODE: ${CMAKE_POSITION_INDEPENDENT_CODE}")
        message(">> CMAKE_SKIP_RPATH: ${CMAKE_SKIP_RPATH}")
        message(">> CMAKE_INSTALL_NAME_DIR: ${CMAKE_INSTALL_NAME_DIR}")

        message(">> CMAKE_MODULE_PATH: ${CMAKE_MODULE_PATH}")
        message(">> CMAKE_PREFIX_PATH: ${CMAKE_PREFIX_PATH}")

        message(">> BUILD_SHARED_LIBS: ${BUILD_SHARED_LIBS}")

        get_directory_property(_COMPILE_DEFS DIRECTORY ${CMAKE_SOURCE_DIR} COMPILE_DEFINITIONS)
        message(">> COMPILE_DEFINITIONS: ${_COMPILE_DEFS}")

        find_package(hello REQUIRED)
        add_library(app_lib app_lib.cpp)
        target_link_libraries(app_lib PRIVATE hello::hello)
        target_compile_definitions(app_lib PRIVATE DEFINITIONS_BOTH="${DEFINITIONS_BOTH}")
        target_compile_definitions(app_lib PRIVATE DEFINITIONS_CONFIG=${DEFINITIONS_CONFIG})

        add_executable(app app.cpp)
        target_link_libraries(app PRIVATE app_lib)
        """)

    def setUp(self):
        self.client = TestClient(path_with_spaces=False)
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            from conans.tools import save
            import os
            class Pkg(ConanFile):
                settings = "build_type"
                def package(self):
                    save(os.path.join(self.package_folder, "include/hello.h"),
                         '#define HELLO_MSG "%s"' % self.settings.build_type)
            """)
        self.client.save({"conanfile.py": conanfile})
        self.client.run("create . hello/0.1@ -s build_type=Debug")
        self.client.run("create . hello/0.1@ -s build_type=Release")

        # Prepare the actual consumer package
        self.client.save({"conanfile.py": self.conanfile,
                          "CMakeLists.txt": self.cmakelist,
                          "app.cpp": self.app,
                          "app_lib.cpp": self.lib_cpp,
                          "app.h": self.lib_h})

    def _run_build(self, settings=None, options=None):
        # Build the profile according to the settings provided
        settings = settings or {}
        settings = " ".join('-s %s="%s"' % (k, v) for k, v in settings.items() if v)
        options = " ".join("-o %s=%s" % (k, v) for k, v in options.items()) if options else ""

        # Run the configure corresponding to this test case
        build_directory = os.path.join(self.client.current_folder, "build").replace("\\", "/")
        with self.client.chdir(build_directory):
            self.client.run("install .. %s %s" % (settings, options))
            install_out = self.client.out
            self.client.run("build ..")
        return install_out


@unittest.skipUnless(platform.system() == "Windows", "Only for windows")
class WinTest(Base):
    @parameterized.expand([("Debug", "MTd", "15", "14", "x86", "v140", True),
                           ("Release", "MD", "15", "17", "x86_64", "", False)])
    def test_toolchain_win(self, build_type, runtime, version, cppstd, arch, toolset, shared):
        settings = {"compiler": "Visual Studio",
                    "compiler.version": version,
                    "compiler.toolset": toolset,
                    "compiler.runtime": runtime,
                    "compiler.cppstd": cppstd,
                    "arch": arch,
                    "build_type": build_type,
                    }
        options = {"shared": shared}
        install_out = self._run_build(settings, options)
        self.assertIn("WARN: Toolchain: Ignoring fPIC option defined for Windows", install_out)

        # FIXME: Hardcoded VS version and partial toolset check
        self.assertIn('CMake command: cmake -G "Visual Studio 15 2017" '
                      '-DCMAKE_TOOLCHAIN_FILE="conan_toolchain.cmake"', self.client.out)
        if toolset == "v140":
            self.assertIn("Microsoft Visual Studio 14.0", self.client.out)
        else:
            self.assertIn("Microsoft Visual Studio/2017", self.client.out)
        if shared:
            self.assertIn("app_lib.dll", self.client.out)
        else:
            self.assertNotIn("app_lib.dll", self.client.out)

        out = str(self.client.out).splitlines()
        runtime = "MT" if "MT" in runtime else "MD"
        generator_platform = "x64" if arch == "x86_64" else "Win32"
        arch = "x64" if arch == "x86_64" else "X86"
        shared_str = "ON" if shared else "OFF"
        vals = {"CMAKE_GENERATOR_PLATFORM": generator_platform,
                "CMAKE_BUILD_TYPE": "",
                "CMAKE_CXX_FLAGS": "/MP1 /DWIN32 /D_WINDOWS /W3 /GR /EHsc",
                "CMAKE_CXX_FLAGS_DEBUG": "/%sd /Zi /Ob0 /Od /RTC1" % runtime,
                "CMAKE_CXX_FLAGS_RELEASE": "/%s /O2 /Ob2 /DNDEBUG" % runtime,
                "CMAKE_C_FLAGS": "/MP1 /DWIN32 /D_WINDOWS /W3",
                "CMAKE_C_FLAGS_DEBUG": "/%sd /Zi /Ob0 /Od /RTC1" % runtime,
                "CMAKE_C_FLAGS_RELEASE": "/%s /O2 /Ob2 /DNDEBUG" % runtime,
                "CMAKE_SHARED_LINKER_FLAGS": "/machine:%s" % arch,
                "CMAKE_EXE_LINKER_FLAGS": "/machine:%s" % arch,
                "CMAKE_CXX_STANDARD": cppstd,
                "CMAKE_CXX_EXTENSIONS": "OFF",
                "BUILD_SHARED_LIBS": shared_str}
        for k, v in vals.items():
            self.assertIn(">> %s: %s" % (k, v), out)

        toolchain = self.client.load("build/conan_toolchain.cmake")
        include = self.client.load("build/conan_project_include.cmake")
        settings["build_type"] = "Release" if build_type == "Debug" else "Debug"
        self._run_build(settings, options)
        # The generated toolchain files must be identical because it is a multi-config
        self.assertEqual(toolchain, self.client.load("build/conan_toolchain.cmake"))
        self.assertEqual(include, self.client.load("build/conan_project_include.cmake"))

        command_str = "build\\Debug\\app.exe"
        self.client.run_command(command_str)
        self.assertIn("Hello: Debug", self.client.out)
        self.assertIn("App: Debug!", self.client.out)
        self.assertIn("DEFINITIONS_BOTH: True", self.client.out)
        self.assertIn("DEFINITIONS_CONFIG: Debug", self.client.out)
        command_str = "build\\Release\\app.exe"
        self.client.run_command(command_str)
        self.assertIn("Hello: Release", self.client.out)
        self.assertIn("App: Release!", self.client.out)
        self.assertIn("DEFINITIONS_BOTH: True", self.client.out)
        self.assertIn("DEFINITIONS_CONFIG: Release", self.client.out)


@unittest.skipUnless(platform.system() == "Linux", "Only for Linux")
class LinuxTest(Base):
    @parameterized.expand([("Debug",  "14", "x86", "libstdc++", True),
                           ("Release", "gnu14", "x86_64", "libstdc++11", False)])
    def test_toolchain_linux(self, build_type, cppstd, arch, libcxx, shared):
        settings = {"compiler": "gcc",
                    "compiler.cppstd": cppstd,
                    "compiler.libcxx": libcxx,
                    "arch": arch,
                    "build_type": build_type}
        self._run_build(settings, {"shared": shared})

        self.assertIn('CMake command: cmake -G "Unix Makefiles" '
                      '-DCMAKE_TOOLCHAIN_FILE="conan_toolchain.cmake"', self.client.out)
        if shared:
            self.assertIn("libapp_lib.so", self.client.out)
        else:
            self.assertIn("libapp_lib.a", self.client.out)

        out = str(self.client.out).splitlines()
        extensions_str = "ON" if "gnu" in cppstd else "OFF"
        pic_str = "" if shared else "ON"
        arch_str = "-m32" if arch == "x86" else "-m64"
        cxx11_abi_str = "1" if libcxx == "libstdc++11" else "0"
        vals = {"CMAKE_CXX_STANDARD": "14",
                "CMAKE_CXX_EXTENSIONS": extensions_str,
                "CMAKE_BUILD_TYPE": build_type,
                "CMAKE_CXX_FLAGS": arch_str,
                "CMAKE_CXX_FLAGS_DEBUG": "-g",
                "CMAKE_CXX_FLAGS_RELEASE": "-O3 -DNDEBUG",
                "CMAKE_C_FLAGS": arch_str,
                "CMAKE_C_FLAGS_DEBUG": "-g",
                "CMAKE_C_FLAGS_RELEASE": "-O3 -DNDEBUG",
                "CMAKE_SHARED_LINKER_FLAGS": arch_str,
                "CMAKE_EXE_LINKER_FLAGS": "",
                "COMPILE_DEFINITIONS": "_GLIBCXX_USE_CXX11_ABI=%s" % cxx11_abi_str,
                "CMAKE_POSITION_INDEPENDENT_CODE": pic_str
                }
        for k, v in vals.items():
            self.assertIn(">> %s: %s" % (k, v), out)

        self.client.run_command("build/app")
        self.assertIn("Hello: %s" % build_type, self.client.out)
        self.assertIn("App: %s!" % build_type, self.client.out)
        self.assertIn("DEFINITIONS_BOTH: True", self.client.out)
        self.assertIn("DEFINITIONS_CONFIG: %s" % build_type, self.client.out)


@unittest.skipUnless(platform.system() == "Darwin", "Only for Apple")
class AppleTest(Base):
    @parameterized.expand([("Debug",  "14",  True),
                           ("Release", "", False)])
    def test_toolchain_apple(self, build_type, cppstd, shared):
        settings = {"compiler": "apple-clang",
                    "compiler.cppstd": cppstd,
                    "build_type": build_type}
        self._run_build(settings, {"shared": shared})

        self.assertIn('CMake command: cmake -G "Unix Makefiles" '
                      '-DCMAKE_TOOLCHAIN_FILE="conan_toolchain.cmake"', self.client.out)
        if shared:
            self.assertIn("libapp_lib.dylib", self.client.out)
        else:
            self.assertIn("libapp_lib.a", self.client.out)

        out = str(self.client.out).splitlines()
        extensions_str = "OFF" if cppstd else ""
        vals = {"CMAKE_CXX_STANDARD": cppstd,
                "CMAKE_CXX_EXTENSIONS": extensions_str,
                "CMAKE_BUILD_TYPE": build_type,
                "CMAKE_CXX_FLAGS": "-m64 -stdlib=libc++",
                "CMAKE_CXX_FLAGS_DEBUG": "-g",
                "CMAKE_CXX_FLAGS_RELEASE": "-O3 -DNDEBUG",
                "CMAKE_C_FLAGS": "-m64",
                "CMAKE_C_FLAGS_DEBUG": "-g",
                "CMAKE_C_FLAGS_RELEASE": "-O3 -DNDEBUG",
                "CMAKE_SHARED_LINKER_FLAGS": "-m64",
                "CMAKE_EXE_LINKER_FLAGS": "",
                "CMAKE_SKIP_RPATH": "1",
                "CMAKE_INSTALL_NAME_DIR": ""
                }
        for k, v in vals.items():
            self.assertIn(">> %s: %s" % (k, v), out)

        if shared:
            build_directory = os.path.join(self.client.current_folder, "build").replace("\\", "/")
            self.client.run_command('DYLD_LIBRARY_PATH="%s" build/app' % build_directory)
        else:
            self.client.run_command('build/app')
        self.assertIn("Hello: %s" % build_type, self.client.out)
        self.assertIn("App: %s!" % build_type, self.client.out)
        self.assertIn("DEFINITIONS_BOTH: True", self.client.out)
        self.assertIn("DEFINITIONS_CONFIG: %s" % build_type, self.client.out)


@attr("toolchain")
class CMakeInstallTest(unittest.TestCase):

    def test_install(self):
        conanfile = textwrap.dedent("""
            from conans import ConanFile, CMake, CMakeToolchain

            class App(ConanFile):
                settings = "os", "arch", "compiler", "build_type"
                exports_sources = "CMakeLists.txt", "header.h"

                def toolchain(self):
                    return CMakeToolchain(self)

                def build(self):
                    cmake = CMake(self)
                    cmake.configure()

                def package(self):
                    cmake = CMake(self)
                    cmake.install()
            """)

        cmakelist = textwrap.dedent("""
            cmake_minimum_required(VERSION 2.8)
            project(App C)

            if(CONAN_TOOLCHAIN_INCLUDED AND CMAKE_VERSION VERSION_LESS "3.15")
                include("${CMAKE_BINARY_DIR}/conan_project_include.cmake")
            endif()

            if(NOT CMAKE_TOOLCHAIN_FILE)
                message(FATAL ">> Not using toolchain")
            endif()

            install(FILES header.h DESTINATION include)
            """)
        client = TestClient(path_with_spaces=False)
        client.save({"conanfile.py": conanfile,
                     "CMakeLists.txt": cmakelist,
                     "header.h": "# my header file"})

        # FIXME: This is broken, because the toolchain at install time, doesn't have the package
        # folder yet. We need to define the layout for local development
        """
        with client.chdir("build"):
            client.run("install ..")
            client.run("build ..")
            client.run("package .. -pf=mypkg")  # -pf=mypkg ignored
        self.assertTrue(os.path.exists(os.path.join(client.current_folder, "build",
                                                    "include", "header.h")))"""

        # The create flow must work
        client.run("create . pkg/0.1@")
        self.assertIn("pkg/0.1 package(): Packaged 1 '.h' file: header.h", client.out)
        ref = ConanFileReference.loads("pkg/0.1")
        layout = client.cache.package_layout(ref)
        package_id = layout.conan_packages()[0]
        package_folder = layout.package(PackageReference(ref, package_id))
        self.assertTrue(os.path.exists(os.path.join(package_folder, "include", "header.h")))
