import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = fileURLToPath(new URL('..', import.meta.url))
const defaultOutDir = join(packageRoot, 'dist')

export async function buildTargets({ outDir = defaultOutDir } = {}) {
  const targetsRoot = join(packageRoot, 'targets')
  const targetDirs = (await readdir(targetsRoot, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort()
  const artifacts = []

  await rm(outDir, { recursive: true, force: true })
  await mkdir(outDir, { recursive: true })
  await cp(join(packageRoot, 'src'), join(outDir, 'src'), { recursive: true })
  await cp(join(packageRoot, 'fixtures'), join(outDir, 'fixtures'), { recursive: true })

  for (const targetDir of targetDirs) {
    const sourceDir = join(targetsRoot, targetDir)
    const manifestPath = join(sourceDir, 'manifest.json')
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
    const outputDir = join(outDir, 'targets', targetDir)
    await mkdir(outputDir, { recursive: true })
    await cp(sourceDir, outputDir, { recursive: true })
    artifacts.push({
      target: manifest.target,
      appTarget: manifest.appTarget,
      displayName: manifest.displayName,
      status: manifest.status,
      capabilities: manifest.capabilities,
      files: [
        relative(outDir, join(outputDir, 'index.html')).replaceAll('\\', '/'),
        relative(outDir, join(outputDir, 'manifest.json')).replaceAll('\\', '/'),
      ],
    })
  }

  const report = {
    generatedAt: 'deterministic-build-report',
    source: 'shared-app-platform-shell-runtime',
    targets: artifacts,
  }
  await writeJson(join(outDir, 'build-report.json'), report)
  return report
}

async function writeJson(path, payload) {
  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, `${JSON.stringify(payload, null, 2)}\n`)
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const report = await buildTargets()
  console.log(`Built ${report.targets.length} app shell targets into ${relative(process.cwd(), defaultOutDir)}`)
}
