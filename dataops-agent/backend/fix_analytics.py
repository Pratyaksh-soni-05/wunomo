import pathlib

f = pathlib.Path('/app/api/v1/analytics.py')
code = f.read_text()

# Fix: safely handle None rows in pip_counts
old = 'pip_counts = {row[0].value: row[1] for row in pip_result.all()}'
new = 'pip_counts = {row[0].value: row[1] for row in pip_result.all() if row[0] is not None}'

if old in code:
    code = code.replace(old, new)
    f.write_text(code)
    print('PATCHED OK - pip_counts fixed')
else:
    print('NOT FOUND - showing lines 60-80:')
    for i, line in enumerate(code.splitlines()[59:80], start=60):
        print(f"  {i}: {repr(line)}")
