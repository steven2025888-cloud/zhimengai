# VitePress 文档项目设置指南

## ✅ 项目已成功配置

织梦AI直播助手的VitePress文档项目已完全配置完毕。

---

## 🚀 快速开始

### 1. 安装依赖（已完成）
```bash
npm install
```

### 2. 本地开发预览
```bash
npm run dev
# 或
npm run docs:dev
```

然后在浏览器中打开 `http://localhost:5173`

### 3. 构建静态网站
```bash
npm run build
# 或
npm run docs:build
```

构建输出在 `.vitepress/dist/` 目录

### 4. 预览构建结果
```bash
npm run preview
# 或
npm run docs:preview
```

---

## 📁 项目结构

```
docs/
├── package.json              # NPM配置
├── .gitignore               # Git忽略文件
├── index.md                 # 首页
├── README.md                # 文档导航
├── .vitepress/
│   ├── config.ts            # VitePress配置
│   └── dist/                # 构建输出目录
└── guide/
    ├── README.md            # 功能总览
    ├── quick-start.md       # 快速开始
    ├── workbench.md         # AI工作台
    ├── keywords.md          # 关键词设置
    ├── anchor.md            # 主播设置
    ├── zhuli.md             # 助播设置
    ├── voice-model.md       # 音色模型
    ├── audio-tools.md       # 音频工具
    ├── ai-reply.md          # AI回复
    ├── script-rewrite.md    # 话术改写
    ├── comment-manager.md   # 评论管理
    ├── public-screen.md     # 公屏轮播
    └── QUICK_REFERENCE.md   # 快速参考卡
```

---

## 📦 已安装的依赖

- **vitepress**: ^1.0.0-rc.31 - VitePress框架
- **vite**: ^4.4.9 - 构建工具
- **vue**: ^3.3.4 - Vue框架

---

## 🌐 部署指南

### 部署到GitHub Pages

1. 在 `.vitepress/config.ts` 中设置 `base` 路径
2. 运行 `npm run build`
3. 将 `.vitepress/dist` 目录推送到GitHub

### 部署到其他服务器

1. 运行 `npm run build` 生成静态文件
2. 将 `.vitepress/dist` 目录上传到服务器
3. 配置Web服务器（Nginx/Apache）指向该目录

### Nginx配置示例

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    root /path/to/docs/.vitepress/dist;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

## 🔧 常用命令

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器 |
| `npm run build` | 构建静态网站 |
| `npm run preview` | 预览构建结果 |
| `npm install` | 安装依赖 |
| `npm update` | 更新依赖 |

---

## 📝 编辑文档

### 添加新页面

1. 在 `guide/` 目录创建新的 `.md` 文件
2. 在 `.vitepress/config.ts` 的 `sidebar` 中添加链接
3. 保存后自动热更新

### 修改配置

编辑 `.vitepress/config.ts` 文件来修改：
- 网站标题和描述
- 导航菜单
- 侧边栏结构
- 主题配置

### 添加图片

1. 将图片放在 `public/` 目录（如果没有则创建）
2. 在Markdown中引用：`![描述](/img/filename.png)`

---

## 🐛 故障排查

### 问题：npm install 失败

**解决方案**：
```bash
# 清除npm缓存
npm cache clean --force

# 重新安装
npm install
```

### 问题：开发服务器无法启动

**解决方案**：
```bash
# 检查端口是否被占用
# 如果5173被占用，VitePress会自动使用其他端口

# 或指定端口
npm run dev -- --port 3000
```

### 问题：构建失败

**解决方案**：
```bash
# 清除构建缓存
rm -rf .vitepress/dist
rm -rf node_modules/.vite

# 重新构建
npm run build
```

---

## 📚 VitePress官方资源

- [VitePress官方文档](https://vitepress.dev/)
- [Markdown扩展](https://vitepress.dev/guide/markdown)
- [主题配置](https://vitepress.dev/reference/site-config)

---

## ✨ 下一步

1. ✅ 运行 `npm run dev` 本地预览文档
2. ✅ 根据需要修改 `.vitepress/config.ts`
3. ✅ 添加更多文档内容
4. ✅ 运行 `npm run build` 生成静态网站
5. ✅ 部署到服务器

---

## 📞 需要帮助？

- 查看 [VitePress官方文档](https://vitepress.dev/)
- 查看项目中的 `README.md` 了解文档结构
- 查看 `guide/QUICK_REFERENCE.md` 获取快速参考

---

**祝你使用愉快！🎉**
