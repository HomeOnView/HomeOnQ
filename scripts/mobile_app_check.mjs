/* Expo 앱 정적 검증: JSX 문법 + 상대 import 해석 + 선언된 의존성 확인
 *
 *   node scripts/mobile_app_check.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as babel from '@babel/parser';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(__dirname, '../mobile-app');
const results = [];
const check = (ok, name, detail = '') => {
  results.push({ ok, name, detail });
  console.log(`${ok ? '  ✅' : '  ❌'} ${name}${detail ? ' — ' + detail : ''}`);
};

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : walk(full);
    return [full];
  });
}

const files = walk(APP).filter((f) => f.endsWith('.js'));
check(files.length >= 8, 'JS 파일 수집', `${files.length}개`);

const imports = new Set();
let syntaxErrors = 0;
for (const file of files) {
  const source = fs.readFileSync(file, 'utf8');
  try {
    const ast = babel.parse(source, {
      sourceType: 'module',
      plugins: ['jsx', 'classProperties', 'optionalChaining', 'nullishCoalescingOperator'],
    });
    for (const node of ast.program.body) {
      if ((node.type === 'ImportDeclaration' || node.type === 'ExportNamedDeclaration') && node.source) {
        imports.add(node.source.value);
      }
      if (node.type === 'ExportDefaultDeclaration' && node.declaration && node.declaration.source) {
        imports.add(node.declaration.source.value);
      }
    }
  } catch (error) {
    syntaxErrors += 1;
    console.log(`     ${path.relative(APP, file)}: ${error.message}`);
  }
}
check(syntaxErrors === 0, 'JSX 문법 파싱', `${files.length}개 파일`);

// 상대 경로 import 실제 존재 확인
let missing = [];
for (const file of files) {
  const source = fs.readFileSync(file, 'utf8');
  const re = /from\s+['"](\.[^'"]+)['"]/g;
  let match;
  while ((match = re.exec(source))) {
    const base = path.resolve(path.dirname(file), match[1]);
    const candidates = [base, base + '.js', base + '.jsx', path.join(base, 'index.js')];
    if (!candidates.some((c) => fs.existsSync(c))) missing.push(`${path.relative(APP, file)} → ${match[1]}`);
  }
}
check(missing.length === 0, '상대 import 파일 존재', missing.join(', '));

// 외부 패키지는 package.json에 선언되어 있어야 Expo 설치 시 해석된다
const pkg = JSON.parse(fs.readFileSync(path.join(APP, 'package.json'), 'utf8'));
const declared = new Set([...Object.keys(pkg.dependencies || {}), ...Object.keys(pkg.devDependencies || {})]);
const builtins = new Set(['react', 'react-native', 'expo', 'expo-status-bar']);
const undeclared = [...imports].filter((spec) => !spec.startsWith('.') && !spec.startsWith('/') && !declared.has(spec.split('/')[0]) && !declared.has(spec) && !builtins.has(spec));
check(undeclared.length === 0, '의존성 선언 확인', undeclared.join(', ') || '모두 선언됨');

// 설정 파일 검증
const appJson = JSON.parse(fs.readFileSync(path.join(APP, 'app.json'), 'utf8'));
check(appJson.expo && appJson.expo.name && appJson.expo.slug, 'app.json 형식', `${appJson.expo.name} / ${appJson.expo.slug}`);
check(fs.existsSync(path.join(APP, 'assets', 'icon.png')), '아이콘 자산 존재');
check(fs.existsSync(path.join(APP, 'babel.config.js')), 'babel.config.js 존재');

// API 연동 코드가 실제 엔드포인트를 쓰는지
const client = fs.readFileSync(path.join(APP, 'src/api/client.js'), 'utf8');
const endpoints = ['/auth/login', '/guardians/me/seniors', '/daily-reports/latest', '/events', '/alerts', '/test-fall', '/demo/simulate'];
const missingEndpoints = endpoints.filter((e) => !client.includes(e));
check(missingEndpoints.length === 0, 'API 엔드포인트 연결', missingEndpoints.join(', ') || '필수 경로 모두 사용');

const passed = results.filter((r) => r.ok).length;
console.log(`\n결과: ${passed}/${results.length} 통과`);
process.exitCode = passed === results.length ? 0 : 1;
