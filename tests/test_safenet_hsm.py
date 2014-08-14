#!/usr/bin/env python

"""Test for check_safenet_hsm.py

  to get detailed output, do this before running:

    export HSM_DEBUG=1
"""
import unittest
import sys, os, time

sys.path.append("../plugins")
from check_safenet_hsm import CheckHsm

class TestCheckHsm(unittest.TestCase):

    def setUp(self):
        print "  in setUp..."
        self.testObj = CheckHsm(diag_tool="./mock_diag.sh")
        #self.testObj = CheckHsm(diag_tool="./mock_diag.sh", diag_list=[2,3,4,5,6,7,8,9,10,11])

    def tearDown(self):
        print "  in tearDown..."
        self.testObj = None

    def testObjectType(self):
        self.assertTrue(isinstance(self.testObj, CheckHsm ))
        
    def testVerify(self):
        self.testObj.verify()

    """ this is needed only if doing <TestCase>.run()
    def runTest(self):
          this lets you control the flow of your test a little more
         -- if u need to test that a method throws an exception

          try:
              self.assertRaises(kerb_utils.KerbPassException, 
                            kerb_utils.KERB_UTILS.is_valid_kerb_password(bad_pass))
          except kerb_utils.KerbPassException:
              pass
          except Exception, e:
              self.fail("unexpected exception: %s" % e)
          else:
              self.fail("expected exception not thrown")
    """
def main():
    """
    this calls  all methods starting w/ 'test...' ; as well as setUp() and tearDown()
    """
    try:
        unittest.main(verbosity=2)  # 0, 1, 2
    except Exception:
        unittest.main()

if __name__ == "__main__":
    main()
