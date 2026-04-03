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
				{ label: 'Documentation', slug: '' },
			],
		}),
	],
});
