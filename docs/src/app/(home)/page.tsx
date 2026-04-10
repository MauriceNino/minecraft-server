import Link from 'next/link';
import {
  BookOpen,
  Container,
  FileCode2,
  GitMerge,
  Plug,
  Rocket,
  Server,
  Settings,
  Zap,
} from 'lucide-react';
import { CodeBlock } from 'fumadocs-ui/components/codeblock';
import { DynamicCodeBlock } from 'fumadocs-ui/components/dynamic-codeblock';

const features = [
  {
    icon: Server,
    title: 'Multi-Platform',
    description: 'Paper, Velocity, and Folia — all centrally managed from one core image.',
  },
  {
    icon: Plug,
    title: 'Plugin Resolution',
    description: 'Modrinth, Hangar, Spiget, and direct URLs with lockfile-based caching.',
  },
  {
    icon: GitMerge,
    title: 'Config Merging',
    description: 'Deep-merge YAML, JSON, TOML, and .properties with sigil-based control.',
  },
  {
    icon: FileCode2,
    title: 'Template Orchestration',
    description: 'Advanced declarative file lifecycles with !replace:, !force:, and !delete: sigils.',
  },
  {
    icon: Settings,
    title: 'Auto-RCON',
    description: 'Automatic RCON bridge injection per platform — zero config needed.',
  },
  {
    icon: Container,
    title: 'Docker-First',
    description: 'Multi-arch images on GHCR and Docker Hub. PID 1 Java handover via os.execvp.',
  },
];

const platforms = [
  { name: 'Paper', color: '#4A90D9' },
  { name: 'Velocity', color: '#1B9CEA' },
  { name: 'Folia', color: '#4ADE80' },
];

const pluginLoaders = [
  { name: 'Modrinth', color: '#4A90D9' },
  { name: 'Hangar', color: '#1B9CEA' },
  { name: 'Spiget', color: '#4ADE80' },
  { name: 'URL', color: '#4ADE80' },
];

const codeSnippet = `services:
  minecraft:
    image: ghcr.io/mauricenino/minecraft-server:latest
    environment:
      TYPE: PAPER
      VERSION: "1.21.4"
      MEMORY: 2G
      PLUGINS: |
        modrinth:luckperms@latest
        modrinth:viaversion@latest
    volumes:
      - ./data:/data/runtime
    ports:
      - "25565:25565"`

export default function HomePage() {
  return (
    <main>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-fd-border">
        <div className="absolute inset-0 bg-linear-to-br from-emerald-500/5 via-transparent to-blue-500/5 dark:from-emerald-500/10 dark:to-blue-500/10" />
        <div className="relative mx-auto max-w-6xl px-6 py-24 text-center md:py-32">
          <h1 className="mb-6 text-4xl font-bold tracking-tight md:text-6xl">
            <span className="bg-linear-to-r from-emerald-500 to-blue-500 bg-clip-text text-transparent">
              MauriceNino/minecraft-server
            </span>
          </h1>
          <p className="mx-auto mb-10 max-w-2xl text-lg text-fd-muted-foreground md:text-xl">
            A modular Python utility and Docker environment to manage
            Minecraft server instances. Dynamic plugin resolution, sigil-based
            config merging, and automated RCON injection.
          </p>
          <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              href="/docs/docker"
              className="inline-flex items-center gap-2 rounded-lg bg-linear-to-r from-emerald-500 to-blue-500 px-6 py-3 text-sm font-medium text-white shadow-lg shadow-emerald-500/25 transition-all hover:shadow-xl hover:shadow-emerald-500/30 hover:brightness-110"
            >
              <Rocket className="h-4 w-4" />
              Get Started
            </Link>
            <Link
              href="/docs"
              className="inline-flex items-center gap-2 rounded-lg border border-fd-border bg-fd-card px-6 py-3 text-sm font-medium text-fd-foreground transition-colors hover:bg-fd-accent"
            >
              <BookOpen className="h-4 w-4" />
              Documentation
            </Link>
          </div>
        </div>
      </section>

      {/* Quick Start */}
      <section className="border-b border-fd-border bg-fd-card/50">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <h2 className="mb-8 text-center text-2xl font-bold">Up and running in seconds</h2>
          <div className="mx-auto max-w-3xl overflow-hidden rounded-xl border border-fd-border bg-fd-background shadow-lg">
            <div className="flex items-center gap-2 border-b border-fd-border px-4 py-3">
              <div className="h-3 w-3 rounded-full bg-red-400" />
              <div className="h-3 w-3 rounded-full bg-yellow-400" />
              <div className="h-3 w-3 rounded-full bg-green-400" />
              <span className="ml-2 text-xs text-fd-muted-foreground font-mono">docker-compose.yml</span>
            </div>
            <pre className="overflow-x-auto text-sm leading-relaxed">
              <DynamicCodeBlock lang="yaml" code={codeSnippet} />
            </pre>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="border-b border-fd-border">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="mb-4 text-center text-2xl font-bold">Everything you need</h2>
          <p className="mb-12 text-center text-fd-muted-foreground">
            One image, every platform, fully automated.
          </p>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="group rounded-xl border border-fd-border bg-fd-card p-6 transition-all hover:border-emerald-500/50 hover:shadow-lg hover:shadow-emerald-500/5"
              >
                <div className="mb-4 inline-flex rounded-lg bg-linear-to-br from-emerald-500/10 to-blue-500/10 p-2.5">
                  <feature.icon className="h-5 w-5 text-emerald-500" />
                </div>
                <h3 className="mb-2 font-semibold">{feature.title}</h3>
                <p className="text-sm leading-relaxed text-fd-muted-foreground">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Supported Platforms */}
      <section className="border-b border-fd-border bg-fd-card/50 py-16 flex flex-col gap-16">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="mb-4 text-center text-2xl font-bold">Supported Platforms</h2>
          <div className="flex flex-wrap items-center justify-center gap-4">
            {platforms.map((platform) => (
              <div
                key={platform.name}
                className="flex items-center gap-2 rounded-full border border-fd-border bg-fd-background px-5 py-2.5 text-sm font-medium transition-all hover:scale-105"
              >
                <div
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: platform.color }}
                />
                {platform.name}
              </div>
            ))}
          </div>
        </div>

        <div className="mx-auto max-w-6xl px-6">
          <h2 className="mb-4 text-center text-2xl font-bold">Supported Plugin Loaders</h2>
          <div className="flex flex-wrap items-center justify-center gap-4">
            {pluginLoaders.map((pluginLoader) => (
              <div
                key={pluginLoader.name}
                className="flex items-center gap-2 rounded-full border border-fd-border bg-fd-background px-5 py-2.5 text-sm font-medium transition-all hover:scale-105"
              >
                <div
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: pluginLoader.color }}
                />
                {pluginLoader.name}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section>
        <div className="mx-auto max-w-6xl px-6 py-20 text-center">
          <h2 className="mb-4 text-2xl font-bold">Ready to get started?</h2>
          <p className="mb-8 text-fd-muted-foreground">
            Check out the docs or explore the example setup.
          </p>
          <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              href="/docs/getting-started"
              className="inline-flex items-center gap-2 rounded-lg bg-linear-to-r from-emerald-500 to-blue-500 px-6 py-3 text-sm font-medium text-white shadow-lg shadow-emerald-500/25 transition-all hover:shadow-xl hover:shadow-emerald-500/30 hover:brightness-110"
            >
              <Rocket className="h-4 w-4" />
              Get Started
            </Link>
            <Link
              href="https://github.com/MauriceNino/minecraft-server/tree/main/examples"
              className="inline-flex items-center gap-2 rounded-lg border border-fd-border bg-fd-card px-6 py-3 text-sm font-medium text-fd-foreground transition-colors hover:bg-fd-accent"
              target="_blank"
              rel="noopener noreferrer"
            >
              <FileCode2 className="h-4 w-4" />
              View Examples
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
