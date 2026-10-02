import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ThreeFileSubmissionTests(unittest.TestCase):
    def test_generated_support_matches_current_helpers(self):
        subprocess.run([sys.executable,str(ROOT/'scripts/build_standalone.py'),'--check'],check=True,capture_output=True)

    def test_flat_three_files_help_and_demo_without_site_packages(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)
            for source in ['src/capstone_compare.py','results/design.md','results/evaluation.md']:
                shutil.copy2(ROOT/source,target/Path(source).name)
            self.assertEqual(len(list(target.iterdir())),3)
            for flag in ['--help','--demo','--requirements']:
                result=subprocess.run([sys.executable,'-I','-S','capstone_compare.py',flag],cwd=target,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                if flag=='--demo':
                    values=json.loads(result.stdout)['result']['nutrients']
                    self.assertEqual(values['energy_kcal'],'160')
                    self.assertEqual(values['sodium_mg'],'60')
            self.assertEqual(len(list(target.iterdir())),3)

    def test_hierarchical_three_files_and_full_calculator_imports(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'submission';target.mkdir()
            for source in ['src/capstone_compare.py','results/design.md','results/evaluation.md']:
                dst=target/source;dst.parent.mkdir(exist_ok=True);shutil.copy2(ROOT/source,dst)
            result=subprocess.run([sys.executable,'-I','-S',str(target/'src/capstone_compare.py'),'--demo'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            # External DB/request are test fixtures, deliberately outside the three-file folder.
            import importlib.util
            spec=importlib.util.spec_from_file_location('synthetic_maker',ROOT/'scripts/make_demo.py')
            maker=importlib.util.module_from_spec(spec);spec.loader.exec_module(maker)
            maker.OUT=Path(d)/'db';maker.main()
            request=Path(d)/'request.json';shutil.copy2(ROOT/'examples/demo.json',request)
            env={**os.environ,'RAG_DATA_DIR':str(maker.OUT),'RAG_CACHE_DIR':str(Path(d)/'cache')}
            result=subprocess.run([sys.executable,'-I',str(target/'src/capstone_compare.py'),'calculate','--request',str(request)],cwd=target,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['items'])
            self.assertEqual(len([p for p in target.rglob('*') if p.is_file()]),3)

if __name__=='__main__':unittest.main()
