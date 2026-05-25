import re

with open("harness/hooks/console.py", "r") as f:
    content = f.read()

content = content.replace('        _stream(_code_preview(code, max_lines=12))\n',
                          '        _stream("")\n        _stream(_code_preview(code, max_lines=12))\n        _stream("")\n')

content = content.replace('        _stream(_code_preview(code, max_lines=8))\n',
                          '        _stream("")\n        _stream(_code_preview(code, max_lines=8))\n        _stream("")\n')

with open("harness/hooks/console.py", "w") as f:
    f.write(content)
