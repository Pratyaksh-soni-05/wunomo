import pathlib

f = pathlib.Path('/app/api/v1/analytics.py')
code = f.read_text()
lines = code.splitlines()

# Show lines 55-130 to see full context
print("=== FULL CONTEXT lines 55-130 ===")
for i, line in enumerate(lines[54:130], start=55):
    print(f"{i}: {repr(line)}")
