// Minimal JSON helper for the DSH lazy pack installer.
// Avoids Windows PowerShell JSON serialization quirks by using Node.
const fs = require('fs');

const LAZY_PLUGINS = [
  'dsh-purge',
  '@wasd258/dsh-prompt-inject',
  'dsh-personal-directive',
  'dsh-infinite-gen-2',
  '@dsh-external/dsh-super-injector',
  '@dsh-external/dsh-shield',
];

function readJson(p) {
  let text = fs.readFileSync(p, 'utf8');
  if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
  return JSON.parse(text);
}

function writeJson(p, obj) {
  fs.writeFileSync(p, JSON.stringify(obj, null, 2) + '\n', 'utf8');
}

const cmd = process.argv[2];

if (cmd === 'get-name') {
  const pkg = readJson(process.argv[3]);
  process.stdout.write(pkg.name || '');
} else if (cmd === 'add-plugin') {
  const profilePath = process.argv[3];
  const pkgName = process.argv[4];
  const linkTarget = process.argv[5];
  const obj = readJson(profilePath);
  obj.dependencies = obj.dependencies || {};
  obj.dependencies[pkgName] = 'link:' + linkTarget;
  // 只有声明了 dsh.bundle 的插件才能进 profile bundles (cordis 补丁插件);
  // 纯 client 插件(如 @wasd258/dsh-prompt-inject) 只加 dependencies, 否则 DSH 启动报
  // "declares no dsh.bundle in its package.json"
  const pkg = readJson(require('path').join(linkTarget, 'package.json'));
  if (pkg.dsh && pkg.dsh.bundle) {
    obj.dsh = obj.dsh || {};
    obj.dsh.profile = obj.dsh.profile || {};
    obj.dsh.profile.bundles = obj.dsh.profile.bundles || [];
    if (!obj.dsh.profile.bundles.includes(pkgName)) {
      obj.dsh.profile.bundles.push(pkgName);
    }
  }
  writeJson(profilePath, obj);
} else if (cmd === 'remove-plugins') {
  const profilePath = process.argv[3];
  const obj = readJson(profilePath);
  obj.dependencies = obj.dependencies || {};
  for (const name of LAZY_PLUGINS) {
    delete obj.dependencies[name];
  }
  obj.dsh = obj.dsh || {};
  obj.dsh.profile = obj.dsh.profile || {};
  obj.dsh.profile.bundles = (obj.dsh.profile.bundles || []).filter((name) => !LAZY_PLUGINS.includes(name));
  writeJson(profilePath, obj);
} else if (cmd === 'write-prompt-config') {
  const mdPath = process.argv[3];
  const cfgPath = process.argv[4];
  const text = fs.readFileSync(mdPath, 'utf8');
  if (fs.existsSync(cfgPath)) {
    const existing = readJson(cfgPath);
    existing.templates = Array.isArray(existing.templates) ? existing.templates : [];
    const found = existing.templates.find((t) => t.id === 'pojia-default');
    if (!found) {
      existing.templates.push({ id: 'pojia-default', name: 'pojia', text, order: 1 });
    } else {
      // v5.2 修复：同 id 覆盖内容，否则重装/升级时旧模板永远卡死（云审指纹残留）
      found.text = text;
    }
    if (!existing.defaultTemplate && existing.templates.length > 0) {
      existing.defaultTemplate = existing.templates[0].id;
    }
    writeJson(cfgPath, existing);
  } else {
    writeJson(cfgPath, {
      templates: [{ id: 'pojia-default', name: 'pojia', text, order: 1 }],
      sessions: {},
      defaultTemplate: 'pojia-default',
    });
  }
} else if (cmd === 'add-template') {
  const mdPath = process.argv[3];
  const cfgPath = process.argv[4];
  const tplId = process.argv[5];
  const tplName = process.argv[6];
  const text = fs.readFileSync(mdPath, 'utf8');
  if (fs.existsSync(cfgPath)) {
    const existing = readJson(cfgPath);
    existing.templates = Array.isArray(existing.templates) ? existing.templates : [];
    const hit = existing.templates.find((t) => t.id === tplId);
    if (hit) {
      hit.name = tplName; hit.text = text; // v5.2 upsert
    } else {
      existing.templates.push({ id: tplId, name: tplName, text, order: 1 });
    }
    writeJson(cfgPath, existing);
  } else {
    writeJson(cfgPath, { templates: [{ id: tplId, name: tplName, text, order: 1 }], sessions: {}, defaultTemplate: tplId });
  }
} else if (cmd === 'registry-add') {
  // registry-add <registryPath> <name> <dir>  —— node 读写，绕开 PowerShell ConvertTo-Json 的 {value,Count} 包裹坑
  const regPath = process.argv[3];
  const name = process.argv[4];
  const dir = process.argv[5];
  let arr = [];
  if (fs.existsSync(regPath)) {
    try {
      let parsed = readJson(regPath);
      // 兼容已被 PS 破坏的 {value:[...],Count:n} 结构：自动解包展平
      if (parsed && !Array.isArray(parsed) && Array.isArray(parsed.value)) parsed = parsed.value;
      if (Array.isArray(parsed)) {
        for (const it of parsed) {
          if (it && Array.isArray(it.value)) arr.push(...it.value); // 展平嵌套 value
          else if (it && it.name) arr.push({ dir: it.dir, name: it.name, at: it.at });
        }
      }
    } catch { arr = []; }
  }
  if (!arr.find((x) => x.name === name)) {
    arr.push({ dir, name, at: new Date().toISOString() });
  } else {
    const e = arr.find((x) => x.name === name); e.dir = dir; e.at = new Date().toISOString();
  }
  writeJson(regPath, arr);
  process.stdout.write('ok');
} else if (cmd === 'registry-remove') {
  // registry-remove <registryPath> <name...>
  const regPath = process.argv[3];
  const drop = new Set(process.argv.slice(4));
  let arr = [];
  if (fs.existsSync(regPath)) {
    try {
      let parsed = readJson(regPath);
      if (parsed && !Array.isArray(parsed) && Array.isArray(parsed.value)) parsed = parsed.value;
      if (Array.isArray(parsed)) {
        for (const it of parsed) {
          if (it && Array.isArray(it.value)) arr.push(...it.value);
          else if (it && it.name) arr.push(it);
        }
      }
    } catch { arr = []; }
  }
  arr = arr.filter((x) => x && x.name && !drop.has(x.name));
  writeJson(regPath, arr);
  process.stdout.write('ok');
} else {
  process.stderr.write('unknown command: ' + cmd + '\n');
  process.exit(1);
}
