import { defineConfig } from "vitepress";
export default defineConfig({
  lang: "zh-CN",
  title: "??AI????",
  description: "????????",
  cleanUrls: true,
  themeConfig: {
    siteTitle: "??AI????",
    nav: [
      { text: "????", link: "/guide/" },
    ],
    sidebar: {
      "/guide/": [
        { text: "????", link: "/guide/" },
        { text: "AI ???", link: "/guide/workbench" },
        { text: "????", link: "/guide/anchor" },
        { text: "?????", link: "/guide/keywords" },
        { text: "????", link: "/guide/zhuli" },
        { text: "????", link: "/guide/voice-model" },
        { text: "??????", link: "/guide/audio-tools" },
        { text: "AI ??", link: "/guide/ai-reply" },
        { text: "????", link: "/guide/script-rewrite" },
        { text: "????", link: "/guide/comment-manager" },
        { text: "????", link: "/guide/public-screen" },
      ],
    },
    footer: {
      message: "?????????",
      copyright: "? ??AI"
    }
  }
});
