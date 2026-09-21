import io
import unittest
from scripts.common import ROOT,dump,source_digest

if __name__=='__main__':
    if not any((ROOT/'tests').glob('test_*.py')):
        raise SystemExit('Test suite omitted from this distribution; restore it before validation.')
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
    text=stream.getvalue()
    print(text)
    (ROOT/'results/environment/unit_tests.txt').write_text(text)
    dump(ROOT/'results/environment/unit_tests.json',dict(passed=result.wasSuccessful(),tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),source_sha256=source_digest()))
    raise SystemExit(0 if result.wasSuccessful() else 1)
