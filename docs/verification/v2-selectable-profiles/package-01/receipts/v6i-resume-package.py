from pathlib import Path
import importlib.util, os, json, subprocess, hashlib, zipfile
ROOT=Path.cwd()
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
b=module('v2_builder_resume',ROOT/'host/packaging/v2/build_windows.py')
h=module('v2_profile_check_resume',ROOT/'host/packaging/v2/profiles_package_check.py')
o=ROOT/'build/v6iw1'; bundle=o/'dist/MotortesterV2'; relocated=o/'Проверка переноса/MotortesterV2'
manifest=b.read_json(bundle/'build-manifest.json'); tree=b.file_tree(bundle)
assert {k:v for k,v in tree.items() if k!='build-manifest.json'}==manifest['files']
assert b.file_tree(relocated)==tree
portable=o/'MotortesterV2-windows-x64.zip'; source=o/'source.zip'
assert b.sha256(source)==manifest['source_archive_sha256']
with zipfile.ZipFile(portable) as z:
    zipped={x.filename.removeprefix('MotortesterV2/'):hashlib.sha256(z.read(x)).hexdigest() for x in z.infolist() if not x.is_dir()}
assert zipped==tree
assert not (o/'frozen-profiles').exists()
rev=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
receipt={'status':'PENDING','failure':'Builder import resolved legacy build_windows before first frozen invocation; exit1. No app or ZIP rebuild.','package_source_commit':manifest['source_commit'],'verifier_source_commit':rev,'portable_sha256_before':b.sha256(portable),'source_sha256_before':b.sha256(source),'tree_before':tree,'verifier_inputs':{str(p.relative_to(ROOT)):b.sha256(p) for p in [ROOT/'host/packaging/v2/build_windows.py',ROOT/'host/packaging/v2/profiles_package_check.py',Path(__file__).resolve()]},'original_build_log_sha256':b.sha256(o/'build.log')}
rp=o/'verification-resume.json'; assert not rp.exists(); b.write_json(rp,receipt)
env=b.clean_environment()
for name in list(env):
    if name.upper()=='PATH': env.pop(name)
env['PATH']=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32')
log=o/'verification-resume.log'
def run(*command,cwd=None,environment=None,timeout=None):
    result=b.run_logged(command,cwd=cwd,env=environment,log=log,timeout=timeout); print(result,end=''); return result
try:
    h.verify_profiles_package(output=o,gui_exe=relocated/'MotortesterV2.exe',relocated=relocated,foreign_cwd=o/'Другая рабочая папка',frozen_env=env,run=run,portable=portable,portable_hash=receipt['portable_sha256_before'],expected_tree=tree,source_archive=source,revision=manifest['source_commit'],exe_hashes={k:tree[k] for k in ('MotortesterV2.exe','MotortesterV2Inspect.exe')},log=log,file_tree=b.file_tree,png_info=b.png_info,read_json=b.read_json,sha256=b.sha256,write_json=b.write_json)
    receipt['status']='PASS'
finally:
    receipt.update(portable_sha256_after=b.sha256(portable),source_sha256_after=b.sha256(source),tree_after_equal=b.file_tree(relocated)==tree)
    b.write_json(rp,receipt)
print(json.dumps({k:v for k,v in receipt.items() if not k.startswith('tree') and k!='verifier_inputs'},indent=2))
