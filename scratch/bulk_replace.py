import re
p = r'C:\Programming\resolve-mcp\scratch\fusion_logoflip\step3_full_build.py'
with open(p, 'r', encoding='utf-8') as f:
    t = f.read()
t = re.sub(r'run\(comp,', 'run(comp_holder,', t)
with open(p, 'w', encoding='utf-8') as f:
    f.write(t)
print('done')
