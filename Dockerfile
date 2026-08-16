# HF Spaces Docker 部署（也可用于任意 VPS）
FROM python:3.11-slim

WORKDIR /app

# 系统依赖（akshare 的 lxml 等需要编译环境；slim 镜像先装基础工具）
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码（libs/ 含补丁版 pandas_ta，随仓库提交）
COPY . .

# HF Spaces 约定：容器监听 7860；自部署时可用 PORT 覆盖
ENV HOST=0.0.0.0 PORT=7860
EXPOSE 7860

# HF 会把 Space secrets 作为环境变量注入（EM_API_KEY / LLM_API_KEY）
CMD ["python", "run.py"]
