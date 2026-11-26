import process from "process";

const port = Number(process.env.GB28181_ENGINE_PORT);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("请通过 GB28181-Analyzer.exe 启动本机分析服务。");
}
export const origin = "http://127.0.0.1:" + port;
