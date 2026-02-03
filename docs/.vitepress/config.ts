import { defineConfig } from "vitepress";
export default defineConfig({
  lang: "zh-CN",
  title: "织梦AI直播助手",
  description: "面向用户的完整功能说明文档",
  cleanUrls: true,
  themeConfig: {
    siteTitle: "织梦AI直播助手",
    nav: [
      { text: "功能总览", link: "/guide/" },
      { text: "快速开始", link: "/guide/quick-start" },
    ],
    sidebar: {
      "/guide/": [
        { text: "功能总览", link: "/guide/" },
        { text: "快速开始", link: "/guide/quick-start" },
        { text: "AI工作台", link: "/guide/workbench" },
        { text: "主播设置", link: "/guide/anchor" },
        { text: "关键词设置", link: "/guide/keywords" },
        { text: "助播设置", link: "/guide/zhuli" },
        { text: "音色模型", link: "/guide/voice-model" },
        { text: "音频目录工具", link: "/guide/audio-tools" },
        { text: "AI回复", link: "/guide/ai-reply" },
        { text: "话术改写", link: "/guide/script-rewrite" },
        { text: "评论管理", link: "/guide/comment-manager" },
        { text: "公屏轮播", link: "/guide/public-screen" },
      ],
    },
    footer: {
      message: "织梦AI直播助手 - 让直播更智能",
      copyright: "© 2024 织梦AI"
    }
  }
});
