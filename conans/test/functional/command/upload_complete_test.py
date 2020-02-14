import json
import os
import platform
import stat
import textwrap
import unittest

import six
from mock import patch
from requests.packages.urllib3.exceptions import ConnectionError

from conans import DEFAULT_REVISION_V1
from conans.client.tools import environment_append
from conans.client.tools.files import untargz
from conans.model.manifest import FileTreeManifest
from conans.model.package_metadata import PackageMetadata
from conans.model.ref import ConanFileReference, PackageReference
from conans.paths import CONANFILE, CONANINFO, CONAN_MANIFEST, EXPORT_TGZ_NAME
from conans.test.utils.cpp_test_files import cpp_hello_conan_files
from conans.test.utils.test_files import hello_conan_files, hello_source_files, temp_folder, \
    uncompress_packaged_files
from conans.test.utils.tools import (NO_SETTINGS_PACKAGE_ID, TestClient, TestRequester, TestServer,
                                     MockedUserIO, TestBufferConanOutput, GenConanfile)
from conans.util.files import load, mkdir, save

myconan1 = """
from conans import ConanFile

class HelloConan(ConanFile):
    name = "Hello"
    version = "1.2.1"
"""


class BadConnectionUploader(TestRequester):
    fail_on = 1

    def __init__(self, *args, **kwargs):
        super(BadConnectionUploader, self).__init__(*args, **kwargs)
        self.counter_fail = 0

    def put(self, *args, **kwargs):
        self.counter_fail += 1
        if self.counter_fail == self.fail_on:
            raise ConnectionError("Can't connect because of the evil mock")
        else:
            return super(BadConnectionUploader, self).put(*args, **kwargs)


class TerribleConnectionUploader(BadConnectionUploader):
    def put(self, *args, **kwargs):
        raise ConnectionError("Can't connect because of the evil mock")


class FailPairFilesUploader(BadConnectionUploader):

    def put(self, *args, **kwargs):
        self.counter_fail += 1
        if self.counter_fail % 2 == 1:
            raise ConnectionError("Pair file, error!")
        else:
            return super(BadConnectionUploader, self).put(*args, **kwargs)


class FailOnReferencesUploader(BadConnectionUploader):
    fail_on = ["lib1", "lib3"]

    def __init__(self, *args, **kwargs):
        super(BadConnectionUploader, self).__init__(*args, **kwargs)

    def put(self, *args, **kwargs):
        if any(ref in args[0] for ref in self.fail_on):
            raise ConnectionError("Connection fails with lib2 and lib4 references!")
        else:
            return super(BadConnectionUploader, self).put(*args, **kwargs)


@unittest.skipIf(TestClient().cache.config.revisions_enabled,
                 "We cannot know the folder of the revision without knowing the hash of "
                 "the contents")
class UploadTest(unittest.TestCase):

    def _get_client(self, requester=None):
        servers = {}
        # All can write (for avoid authentication until we mock user_io)
        self.test_server = TestServer([("*/*@*/*", "*")], [("*/*@*/*", "*")],
                                      users={"lasote": "mypass"})
        servers["default"] = self.test_server
        return TestClient(servers=servers, users={"default": [("lasote", "mypass")]},
                          requester_class=requester)

    def setUp(self):
        self.client = self._get_client()
        self.ref = ConanFileReference.loads("Hello/1.2.1@frodo/stable#%s" %
                                            DEFAULT_REVISION_V1)
        self.pref = PackageReference(self.ref, "myfakeid", DEFAULT_REVISION_V1)
        reg_folder = self.client.cache.package_layout(self.ref).export()

        self.client.run('upload %s' % str(self.ref), assert_error=True)
        self.assertIn("ERROR: Recipe not found: '%s'" % str(self.ref), self.client.out)

        files = hello_source_files()

        fake_metadata = PackageMetadata()
        fake_metadata.recipe.revision = DEFAULT_REVISION_V1
        fake_metadata.packages[self.pref.id].revision = DEFAULT_REVISION_V1
        self.client.save({"metadata.json": fake_metadata.dumps()},
                         path=self.client.cache.package_layout(self.ref).base_folder())
        self.client.save(files, path=reg_folder)
        self.client.save({CONANFILE: myconan1,
                          "include/math/lib1.h": "//copy",
                          "my_lib/debug/libd.a": "//copy",
                          "my_data/readme.txt": "//copy",
                          "my_bin/executable": "//copy"}, path=reg_folder)
        mkdir(self.client.cache.package_layout(self.ref).export_sources())
        manifest = FileTreeManifest.create(reg_folder)
        manifest.time = '123123123'
        manifest.save(reg_folder)
        self.test_server.server_store.update_last_revision(self.ref)

        self.server_pack_folder = self.test_server.server_store.package(self.pref)

        package_folder = self.client.cache.package_layout(self.ref).package(self.pref)
        save(os.path.join(package_folder, "include", "lib1.h"), "//header")
        save(os.path.join(package_folder, "lib", "my_lib", "libd.a"), "//lib")
        save(os.path.join(package_folder, "res", "shares", "readme.txt"),
             "//res")
        save(os.path.join(package_folder, "bin", "my_bin", "executable"), "//bin")
        save(os.path.join(package_folder, CONANINFO),
             """[recipe_hash]\n%s""" % manifest.summary_hash)
        FileTreeManifest.create(package_folder).save(package_folder)
        self.test_server.server_store.update_last_package_revision(self.pref)

        os.chmod(os.path.join(package_folder, "bin", "my_bin", "executable"),
                 os.stat(os.path.join(package_folder, "bin", "my_bin", "executable")).st_mode |
                 stat.S_IRWXU)

        expected_manifest = FileTreeManifest.create(package_folder)
        expected_manifest.save(package_folder)

        self.server_reg_folder = self.test_server.server_store.export(self.ref)
        self.assertFalse(os.path.exists(self.server_reg_folder))
        self.assertFalse(os.path.exists(self.server_pack_folder))

    def try_upload_bad_recipe_test(self):
        files = hello_conan_files("Hello0", "1.2.1")
        self.client.save(files)
        self.client.run("export . frodo/stable")
        ref = ConanFileReference.loads("Hello0/1.2.1@frodo/stable")
        os.unlink(os.path.join(self.client.cache.package_layout(ref).export(), CONAN_MANIFEST))
        with six.assertRaisesRegex(self, Exception, "Command failed"):
            self.client.run("upload %s" % str(ref))

        self.assertIn("Cannot upload corrupted recipe", self.client.out)

    def upload_with_pattern_test(self):
        for num in range(5):
            files = hello_conan_files("Hello%s" % num, "1.2.1")
            self.client.save(files)
            self.client.run("export . frodo/stable")

        self.client.run("upload Hello* --confirm")
        for num in range(5):
            self.assertIn("Uploading Hello%s/1.2.1@frodo/stable" % num, self.client.out)

        self.client.run("upload Hello0* --confirm")
        self.assertIn("Uploading Hello0/1.2.1@frodo/stable",
                      self.client.out)
        self.assertIn("Recipe is up to date, upload skipped", self.client.out)
        self.assertNotIn("Hello1", self.client.out)
        self.assertNotIn("Hello2", self.client.out)
        self.assertNotIn("Hello3", self.client.out)

    def upload_error_test(self):
        """Cause an error in the transfer and see some message"""

        # Check for the default behaviour
        client = self._get_client(BadConnectionUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run("upload Hello* --confirm")
        self.assertIn("Can't connect because of the evil mock", client.out)
        self.assertIn("Waiting 5 seconds to retry...", client.out)

        # This will fail in the first put file, so, as we need to
        # upload 3 files (conanmanifest, conanfile and tgz) will do it with 2 retries
        client = self._get_client(BadConnectionUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run("upload Hello* --confirm --retry-wait=0")
        self.assertIn("Can't connect because of the evil mock", client.out)
        self.assertIn("Waiting 0 seconds to retry...", client.out)

        # but not with 0
        client = self._get_client(BadConnectionUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run("upload Hello* --confirm --retry 0 --retry-wait=1", assert_error=True)
        self.assertNotIn("Waiting 1 seconds to retry...", client.out)
        self.assertIn("ERROR: Hello0/1.2.1@frodo/stable: Upload recipe to 'default' failed: "
                      "Execute upload again to retry upload the failed files: "
                      "conan_export.tgz. [Remote: default]", client.out)

        # Try with broken connection even with 10 retries
        client = self._get_client(TerribleConnectionUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run("upload Hello* --confirm --retry 10 --retry-wait=0", assert_error=True)
        self.assertIn("Waiting 0 seconds to retry...", client.out)
        self.assertIn("ERROR: Hello0/1.2.1@frodo/stable: Upload recipe to 'default' failed: "
                      "Execute upload again to retry upload the failed files", client.out)

        # For each file will fail the first time and will success in the second one
        client = self._get_client(FailPairFilesUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run("install Hello0/1.2.1@frodo/stable --build")
        client.run("upload Hello* --confirm --retry 3 --retry-wait=0 --all")
        self.assertEqual(str(client.out).count("ERROR: Pair file, error!"), 6)

    def upload_error_with_config_test(self):
        """Cause an error in the transfer and see some message"""

        # This will fail in the first put file, so, as we need to
        # upload 3 files (conanmanifest, conanfile and tgz) will do it with 2 retries
        client = self._get_client(BadConnectionUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run('config set general.retry_wait=0')
        client.run("upload Hello* --confirm")
        self.assertIn("Can't connect because of the evil mock", client.out)
        self.assertIn("Waiting 0 seconds to retry...", client.out)

        # but not with 0
        client = self._get_client(BadConnectionUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run('config set general.retry=0')
        client.run('config set general.retry_wait=1')
        client.run("upload Hello* --confirm", assert_error=True)
        self.assertNotIn("Waiting 1 seconds to retry...", client.out)
        self.assertIn("ERROR: Hello0/1.2.1@frodo/stable: Upload recipe to 'default' failed: "
                      "Execute upload again to retry upload the failed files: "
                      "conan_export.tgz. [Remote: default]", client.out)

        # Try with broken connection even with 10 retries
        client = self._get_client(TerribleConnectionUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run('config set general.retry=10')
        client.run('config set general.retry_wait=0')
        client.run("upload Hello* --confirm", assert_error=True)
        self.assertIn("Waiting 0 seconds to retry...", client.out)
        self.assertIn("ERROR: Hello0/1.2.1@frodo/stable: Upload recipe to 'default' failed: "
                      "Execute upload again to retry upload the failed files", client.out)

        # For each file will fail the first time and will success in the second one
        client = self._get_client(FailPairFilesUploader)
        files = cpp_hello_conan_files("Hello0", "1.2.1", build=False)
        client.save(files)
        client.run("export . frodo/stable")
        client.run("install Hello0/1.2.1@frodo/stable --build")
        client.run('config set general.retry=3')
        client.run('config set general.retry_wait=0')
        client.run("upload Hello* --confirm --all")
        self.assertEqual(str(client.out).count("ERROR: Pair file, error!"), 6)

    def upload_parallel_error_test(self):
        """Cause an error in the parallel transfer and see some message"""
        client = TestClient(requester_class=FailOnReferencesUploader, default_server_user=True)
        client.save({"conanfile.py": GenConanfile()})
        client.run('user -p password -r default user')
        for index in range(4):
            client.run('create . lib{}/1.0@user/channel'.format(index))
        client.run('upload lib* --parallel -c --all -r default', assert_error=True)
        self.assertIn("Connection fails with lib2 and lib4 references!", client.out)
        self.assertIn("Execute upload again to retry upload the failed files", client.out)

    def upload_parallel_success_test(self):
        """Upload 2 packages in parallel with success"""

        client = TestClient(default_server_user=True)
        client.save({"conanfile.py": GenConanfile()})
        client.run('create . lib0/1.0@user/channel')
        self.assertIn("lib0/1.0@user/channel: Package '{}' created".format(NO_SETTINGS_PACKAGE_ID),
                      client.out)
        client.run('create . lib1/1.0@user/channel')
        self.assertIn("lib1/1.0@user/channel: Package '{}' created".format(NO_SETTINGS_PACKAGE_ID),
                      client.out)
        client.run('user -p password -r default user')
        client.run('upload lib* --parallel -c --all -r default')
        self.assertIn("Uploading lib0/1.0@user/channel to remote 'default'", client.out)
        self.assertIn("Uploading lib1/1.0@user/channel to remote 'default'", client.out)
        client.run('search lib0/1.0@user/channel -r default')
        self.assertIn("lib0/1.0@user/channel", client.out)
        client.run('search lib1/1.0@user/channel -r default')
        self.assertIn("lib1/1.0@user/channel", client.out)

    def upload_parallel_fail_on_interaction_test(self):
        """Upload 2 packages in parallel and fail because non_interactive forced"""

        client = TestClient(default_server_user=True)
        client.save({"conanfile.py": GenConanfile()})
        num_references = 2
        for index in range(num_references):
            client.run('create . lib{}/1.0@user/channel'.format(index))
            self.assertIn("lib{}/1.0@user/channel: Package '{}' created".format(
                index,
                NO_SETTINGS_PACKAGE_ID),
                client.out)
        client.run('user -c')
        client.run('upload lib* --parallel -c --all -r default', assert_error=True)
        self.assertIn("ERROR: lib0/1.0@user/channel: Upload recipe to 'default' failed: "
                      "Conan interactive mode disabled. [Remote: default]", client.out)

    def recipe_upload_fail_on_generic_exception_test(self):
        # Make the upload fail with a generic Exception
        client = TestClient(default_server_user=True)
        conanfile = textwrap.dedent("""
            import os
            from conans import ConanFile
            class Pkg(ConanFile):
                exports = "*"
                def package(self):
                    self.copy("*")
            """)
        client.save({"conanfile.py": conanfile,
                     "myheader.h": "",
                     "conan_export.tgz/dummy": ""})
        client.run('create . lib/1.0@user/channel')
        client.run('upload lib* -c --all -r default', assert_error=True)
        self.assertIn("ERROR: lib/1.0@user/channel: Upload recipe to 'default' failed:", client.out)
        self.assertIn("ERROR: Errors uploading some packages", client.out)

    def package_upload_fail_on_generic_exception_test(self):
        # Make the upload fail with a generic Exception
        client = TestClient(default_server_user=True)
        conanfile = textwrap.dedent("""
            import os
            from conans import ConanFile
            class Pkg(ConanFile):
                exports = "*"
                def package(self):
                    os.makedirs(os.path.join(self.package_folder, "conan_package.tgz"))
                    self.copy("*")
            """)
        client.save({"conanfile.py": conanfile,
                     "myheader.h": ""})
        client.run('create . lib/1.0@user/channel')

        client.run('upload lib* -c --all -r default', assert_error=True)
        self.assertNotIn("os.remove(tgz_path)", client.out)
        self.assertNotIn("Traceback", client.out)
        self.assertIn("ERROR: lib/1.0@user/channel:5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9: "
                      "Upload package to 'default' failed:", client.out)
        self.assertIn("ERROR: Errors uploading some packages", client.out)

        with environment_append({"CONAN_VERBOSE_TRACEBACK": "True"}):
            client.run('upload lib* -c --all -r default', assert_error=True)
            self.assertIn("os.remove(tgz_path)", client.out)
            self.assertIn("Traceback", client.out)
            self.assertIn("ERROR: lib/1.0@user/channel:5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9: "
                          "Upload package to 'default' failed:", client.out)
            self.assertIn("ERROR: Errors uploading some packages", client.out)

    def test_beat_character_long_upload(self):
        client = TestClient(default_server_user=True)
        slow_conanfile = textwrap.dedent("""
            from conans import ConanFile
            class MyPkg(ConanFile):
                exports = "*"
                def package(self):
                    self.copy("*")
            """)
        client.save({"conanfile.py": slow_conanfile,
                     "hello.cpp": ""})
        client.run("create . pkg/0.1@user/stable")
        client.run("user user --password=password")
        with patch("conans.util.progress_bar.TIMEOUT_BEAT_SECONDS", -1):
            with patch("conans.util.progress_bar.TIMEOUT_BEAT_CHARACTER", "%&$"):
                client.run("upload pkg/0.1@user/stable --all")
        out = "".join(str(client.out).splitlines())
        self.assertIn("Compressing package...%&$%&$Uploading conan_package.tgz -> "
                      "pkg/0.1@user/stable:5ab8", out)
        self.assertIn("%&$Uploading conan_export.tgz", out)
        self.assertIn("%&$Uploading conaninfo.txt", out)

    def upload_with_pattern_and_package_error_test(self):
        files = hello_conan_files("Hello1", "1.2.1")
        self.client.save(files)
        self.client.run("export . frodo/stable")

        self.client.run("upload Hello* --confirm -p 234234234", assert_error=True)
        self.assertIn("-p parameter only allowed with a valid recipe reference",
                      self.client.out)

    def check_upload_confirm_question_test(self):
        user_io = MockedUserIO({"default": [("lasote", "mypass")]}, out=TestBufferConanOutput())
        files = hello_conan_files("Hello1", "1.2.1")
        self.client.save(files)
        self.client.run("export . frodo/stable")

        user_io.request_string = lambda _: "y"
        self.client.run("upload Hello*", user_io=user_io)
        self.assertIn("Uploading Hello1/1.2.1@frodo/stable", self.client.out)

        files = hello_conan_files("Hello2", "1.2.1")
        self.client.save(files)
        self.client.run("export . frodo/stable")

        user_io.request_string = lambda _: "n"
        self.client.run("upload Hello*", user_io=user_io)
        self.assertNotIn("Uploading Hello2/1.2.1@frodo/stable", self.client.out)

    def upload_same_package_dont_compress_test(self):
        # Create a manifest for the faked package
        pack_path = self.client.cache.package_layout(self.pref.ref).package(self.pref)
        package_path = self.client.cache.package_layout(self.pref.ref).package(self.pref)
        expected_manifest = FileTreeManifest.create(package_path)
        expected_manifest.save(pack_path)

        self.client.run("upload %s --all" % str(self.ref))
        self.assertIn("Compressing recipe", self.client.out)
        self.assertIn("Compressing package", str(self.client.out))

        self.client.run("upload %s --all" % str(self.ref))
        self.assertNotIn("Compressing recipe", self.client.out)
        self.assertNotIn("Compressing package", str(self.client.out))
        self.assertIn("Package is up to date", str(self.client.out))

    def upload_with_no_valid_settings_test(self):
        '''Check if upload is still working even if the specified setting is not valid.
        If this test fails, will fail in Linux/OSx'''
        conanfile = """
from conans import ConanFile
class TestConan(ConanFile):
    name = "Hello"
    version = "1.2"
    settings = {"os": ["Windows"]}
"""
        files = {CONANFILE: conanfile}
        self.client.save(files)
        self.client.run("export . lasote/stable")
        self.assertIn("WARN: Conanfile doesn't have 'license'", self.client.out)
        self.client.run("upload Hello/1.2@lasote/stable")
        self.assertIn("Uploading conanmanifest.txt", self.client.out)

    def single_binary_test(self):
        """ basic installation of a new conans
        """
        # Try to upload an package without upload conans first
        self.client.run('upload %s -p %s' % (self.ref, str(self.pref.id)))
        self.assertIn("Uploaded conan recipe '%s'" % str(self.ref), self.client.out)

    def simple_test(self):
        """ basic installation of a new conans
        """
        # Upload conans
        self.client.run('upload %s' % str(self.ref))
        self.server_reg_folder = self.test_server.server_store.export(self.ref)

        self.assertTrue(os.path.exists(self.server_reg_folder))
        if not self.client.cache.config.revisions_enabled:
            self.assertFalse(os.path.exists(self.server_pack_folder))

        # Upload package
        self.client.run('upload %s -p %s' % (str(self.ref), str(self.pref.id)))

        self.server_pack_folder = self.test_server.server_store.package(self.pref)

        self.assertTrue(os.path.exists(self.server_reg_folder))
        self.assertTrue(os.path.exists(self.server_pack_folder))

        # Test the file in the downloaded conans
        files = ['CMakeLists.txt',
                 'my_lib/debug/libd.a',
                 'hello.cpp',
                 'hello0.h',
                 CONANFILE,
                 CONAN_MANIFEST,
                 'main.cpp',
                 'include/math/lib1.h',
                 'my_data/readme.txt',
                 'my_bin/executable']

        self.assertTrue(os.path.exists(os.path.join(self.server_reg_folder, CONANFILE)))
        self.assertTrue(os.path.exists(os.path.join(self.server_reg_folder, EXPORT_TGZ_NAME)))
        tmp = temp_folder()
        untargz(os.path.join(self.server_reg_folder, EXPORT_TGZ_NAME), tmp)
        for f in files:
            if f not in (CONANFILE, CONAN_MANIFEST):
                self.assertTrue(os.path.exists(os.path.join(tmp, f)))
            else:
                self.assertFalse(os.path.exists(os.path.join(tmp, f)))

        folder = uncompress_packaged_files(self.test_server.server_store, self.pref)

        self.assertTrue(os.path.exists(os.path.join(folder,
                                                    "include",
                                                    "lib1.h")))
        self.assertTrue(os.path.exists(os.path.join(folder,
                                                    "lib",
                                                    "my_lib/libd.a")))
        self.assertTrue(os.path.exists(os.path.join(folder,
                                                    "res",
                                                    "shares/readme.txt")))

        if platform.system() != "Windows":
            self.assertEqual(os.stat(os.path.join(folder,
                                                  "bin",
                                                  "my_bin/executable")).st_mode &
                             stat.S_IRWXU, stat.S_IRWXU)

    def upload_all_test(self):
        """Upload conans and package together"""
        # Try to upload all conans and packages
        self.client.run('user -p mypass -r default lasote')
        self.client.run('upload %s --all' % str(self.ref))
        lines = [line.strip() for line in str(self.client.out).splitlines()
                 if line.startswith("Uploading")]
        self.assertEqual(lines, ["Uploading to remote 'default':",
                                 "Uploading Hello/1.2.1@frodo/stable to remote 'default'",
                                 "Uploading conan_export.tgz -> Hello/1.2.1@frodo/stable",
                                 "Uploading conanfile.py -> Hello/1.2.1@frodo/stable",
                                 "Uploading conanmanifest.txt -> Hello/1.2.1@frodo/stable",
                                 "Uploading package 1/1: myfakeid to 'default'",
                                 "Uploading conan_package.tgz -> Hello/1.2.1@frodo/stable:myfa",
                                 "Uploading conaninfo.txt -> Hello/1.2.1@frodo/stable:myfa",
                                 "Uploading conanmanifest.txt -> Hello/1.2.1@frodo/stable:myfa",
                                 ])
        if self.client.cache.config.revisions_enabled:
            layout = self.client.cache.package_layout(self.ref)
            rev = layout.recipe_revision()
            self.ref = self.ref.copy_with_rev(rev)
            prev = layout.package_revision(self.pref)
            self.pref = self.pref.copy_with_revs(rev, prev)

        server_reg_folder = self.test_server.server_store.export(self.ref)
        server_pack_folder = self.test_server.server_store.package(self.pref)

        self.assertTrue(os.path.exists(server_reg_folder))
        self.assertTrue(os.path.exists(server_pack_folder))

    def force_test(self):
        '''Tries to upload a conans exported after than remote version.'''
        # Upload all conans and packages
        self.client.run('upload %s --all' % str(self.ref))

        if self.client.cache.config.revisions_enabled:
            layout = self.client.cache.package_layout(self.ref)
            rev = layout.recipe_revision()
            self.ref = self.ref.copy_with_rev(rev)
            prev = layout.package_revision(self.pref)
            self.pref = self.pref.copy_with_revs(rev, prev)

        self.server_reg_folder = self.test_server.server_store.export(self.ref)
        self.server_pack_folder = self.test_server.server_store.package(self.pref)

        self.assertTrue(os.path.exists(self.server_reg_folder))
        self.assertTrue(os.path.exists(self.server_pack_folder))

        # Fake datetime from exported date and upload again

        old_digest = self.client.cache.package_layout(self.ref).recipe_manifest()
        old_digest.file_sums["new_file"] = "012345"
        fake_digest = FileTreeManifest(2, old_digest.file_sums)
        fake_digest.save(self.client.cache.package_layout(self.ref).export())

        self.client.run('upload %s' % str(self.ref), assert_error=True)
        self.assertIn("Remote recipe is newer than local recipe", self.client.out)

        self.client.run('upload %s --force' % str(self.ref))
        self.assertIn("Uploading %s" % str(self.ref),
                      self.client.out)

        # Repeat transfer, to make sure it is uploading again
        self.client.run('upload %s --force' % str(self.ref))
        self.assertIn("Uploading conan_export.tgz", self.client.out)
        self.assertIn("Uploading conanfile.py", self.client.out)

    def upload_json_test(self):
        conanfile = """
from conans import ConanFile

class TestConan(ConanFile):
    name = "test"
    version = "0.1"

    def package(self):
        self.copy("mylib.so", dst="lib")
"""

        client = self._get_client()
        client.save({"conanfile.py": conanfile,
                     "mylib.so": ""})
        client.run("create . danimtb/testing")

        # Test conflict parameter error
        client.run("upload test/0.1@danimtb/* --all -p ewvfw --json upload.json", assert_error=True)

        json_path = os.path.join(client.current_folder, "upload.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        self.assertTrue(output["error"])
        self.assertEqual(0, len(output["uploaded"]))

        # Test invalid reference error
        client.run("upload fake/0.1@danimtb/testing --all --json upload.json", assert_error=True)
        json_path = os.path.join(client.current_folder, "upload.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        self.assertTrue(output["error"])
        self.assertEqual(0, len(output["uploaded"]))

        # Test normal upload
        client.run("upload test/0.1@danimtb/testing --all --json upload.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        output_expected = {"error": False,
                           "uploaded": [
                               {
                                   "recipe": {
                                       "id": "test/0.1@danimtb/testing",
                                       "remote_url": "unknown",
                                       "remote_name": "default",
                                       "time": "unknown"
                                   },
                                   "packages": [
                                       {
                                           "id": NO_SETTINGS_PACKAGE_ID,
                                           "time": "unknown"
                                       }
                                   ]
                               }
                           ]}
        self.assertEqual(output_expected["error"], output["error"])
        self.assertEqual(len(output_expected["uploaded"]), len(output["uploaded"]))

        for i, item in enumerate(output["uploaded"]):
            self.assertEqual(output_expected["uploaded"][i]["recipe"]["id"], item["recipe"]["id"])
            self.assertEqual(output_expected["uploaded"][i]["recipe"]["remote_name"],
                             item["recipe"]["remote_name"])
            for j, subitem in enumerate(item["packages"]):
                self.assertEqual(output_expected["uploaded"][i]["packages"][j]["id"],
                                 subitem["id"])
