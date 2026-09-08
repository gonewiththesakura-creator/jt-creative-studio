from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SOURCE=(ROOT/'sources/video_business.js').read_text(encoding='utf8')
CONFIG=(ROOT/'config.json').read_text(encoding='utf8')
checks={
 'boolean controls':all(x in SOURCE for x in ['p.type===\'boolean\'','inp.type=\'checkbox\'','inp.checked']),
 'select controls':all(x in SOURCE for x in ['p.type===\'select\'','p.options','option.value']),
 'numeric metadata':all(x in SOURCE for x in ['p.min','p.max','inp.min','inp.max']),
 'native value collection':all(x in SOURCE for x in ['readParamValue','el.checked','Number.parseInt']),
 'false and zero retained':"value!==''" in SOURCE and 'if(el)' in SOURCE,
 'unavailable feature notice':'fixed_features' in SOURCE and '当前API图不包含' in CONFIG,
 'scail names in config':all(x in CONFIG for x in ['SCAIL2 Plus','SCAIL2 · 动作迁移/人物替换']),
 'technical controls hidden':all(x not in SOURCE for x in ['blocks_to_swap','load_device','scheduler']),
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
