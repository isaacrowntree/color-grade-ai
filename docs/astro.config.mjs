// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
	site: 'https://isaacrowntree.github.io',
	base: '/color-grade-ai',
	integrations: [
		starlight({
			title: 'color-grade-ai',
			description: 'AI-powered .cube LUT generation for DaVinci Resolve and Premiere Pro',
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/isaacrowntree/color-grade-ai' }],
			sidebar: [
				{ label: 'Getting Started', slug: 'getting-started' },
				{
					label: 'Guides',
					items: [
						{ label: 'DaVinci Resolve', slug: 'guides/davinci-resolve' },
						{ label: 'Adobe Premiere Pro', slug: 'guides/premiere-pro' },
						{ label: 'Using with Claude Code', slug: 'guides/claude-code' },
					],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'LUT Types', slug: 'reference/lut-types' },
						{ label: 'Preset Configuration', slug: 'reference/presets-config' },
						{ label: 'Frame Analysis', slug: 'reference/analyze-frame' },
						{ label: 'Color Science', slug: 'reference/color-science' },
					],
				},
			],
		}),
	],
});
