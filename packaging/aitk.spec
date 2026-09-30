# PyInstaller recipe for the one-file build. Run from the repo root:
#   pyinstaller packaging/aitk.spec
# The result is dist/aitk (dist/aitk.exe on Windows): the whole kit in one file, no Python needed.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("aitk", includes=["connect/recipes/*.toml", "guide/lessons/*.md", "guide/prompts/*.md"])
hiddenimports = collect_submodules("keyring.backends") + collect_submodules("aitk")

a = Analysis(["entry.py"], pathex=["../src"], datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "unittest", "pydoc", "doctest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="aitk", console=True, upx=False,
          disable_windowed_traceback=False)
