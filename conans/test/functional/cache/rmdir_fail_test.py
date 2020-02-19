import os
import platform
import unittest

from conans.model.ref import ConanFileReference
from conans.test.utils.tools import TestClient, GenConanfile


class RMdirFailTest(unittest.TestCase):

    @unittest.skipIf(platform.system() != "Windows", "needs windows")
    def fail_rmdir_test(self):
        client = TestClient()
        client.save({"conanfile.py": GenConanfile()})
        client.run("create . MyPkg/0.1@lasote/testing")
        ref = ConanFileReference.loads("MyPkg/0.1@lasote/testing")
        builds = client.cache.package_layout(ref).builds()
        build_folder = os.listdir(builds)[0]
        build_folder = os.path.join(builds, build_folder)
        f = open(os.path.join(build_folder, "myfile"), "wb")
        f.write(b"Hello world")
        client.run("install MyPkg/0.1@lasote/testing --build", assert_error=True)
        self.assertIn("Couldn't remove folder, might be busy or open", client.out)
