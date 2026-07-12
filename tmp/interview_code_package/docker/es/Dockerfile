# 基于 Docker Hub ES 8.17.0 安装 IK 中文分词插件
# Docker Hub 镜像在国内容易通过镜像加速器访问
FROM elasticsearch:8.17.0

# analysis-ik 版本需与 ES 版本严格一致
# 从 GitHub releases 下载（国内可能需要代理）
RUN bin/elasticsearch-plugin install --batch \
    https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-8.17.0.zip
