import { mount, signal, Text, View, WebView } from "nsh";
import { AlertDialog, TitleBar } from "nsh/base";
import { Application, Window } from "nsh/desktop";
import { origin } from "./engine";

function Workspace() {
  const failed = signal(false);
  const loaded = signal(false);
  const busy = signal(false);
  const installing = signal(false);
  let confirming = false;

  async function requestClose() {
    if (confirming) return;
    if (installing()) {
      confirming = true;
      try {
        await AlertDialog.show({
          title: "正在安装分析工具",
          description: "请完成 Windows 安装提示，等待工具状态刷新后再退出。",
          actions: [{ id: "stay", label: "返回设置", role: "cancel" }],
        });
      } finally {
        confirming = false;
      }
      return;
    }
    if (busy()) {
      confirming = true;
      try {
        const answer = await AlertDialog.show({
          title: "分析任务仍在运行",
          description: "现在退出会中断本机分析。",
          actions: [
            { id: "stay", label: "继续分析", role: "cancel" },
            { id: "exit", label: "退出工作台", role: "destructive" },
          ],
        });
        if (answer.action !== "exit") return;
      } finally {
        confirming = false;
      }
    }
    Application.quit();
  }

  function receive({ data }: { data: string }) {
    if (data === "workspace-ready") loaded.set(true);
    if (data === "analysis-busy") busy.set(true);
    if (data === "analysis-idle") busy.set(false);
    if (data === "install-busy") installing.set(true);
    if (data === "install-idle") installing.set(false);
  }

  Application.on("quitRequest", requestClose);
  return <Window id="main" title={loaded() ? "GB28181 Analyzer · 视联网分析工作台" : "GB28181 Analyzer · 正在连接"}
                 titleBar={{ style: "hidden" }} closeOnPress={false} onClosePress={requestClose}>
    <View class="flex-1 bg-background">
      <TitleBar class="flex-row items-center gap-3 bg-red-950 px-5">
        <Text class="text-sm font-bold text-white">GB28181</Text>
        <Text class="text-xs text-red-100">视联网诊断工作台</Text>
      </TitleBar>
      {failed() ? <View class="flex-1 justify-center items-center gap-4">
        <Text class="text-lg text-foreground">无法打开本机分析工作台</Text>
        <Text class="text-foreground">请检查分析服务和 Microsoft Edge WebView2 Runtime。</Text>
        <View role="button" class="rounded-lg bg-red-700 px-5 py-2 active:opacity-75" onPress={() => failed.set(false)}>
          <Text class="text-white">重新连接</Text>
        </View>
      </View> : <WebView testID={loaded() ? "workspace-loaded" : "workspace-loading"}
                        class="flex-1" src={origin} allowOrigin={origin} onMessage={receive}
                        onError={() => { loaded.set(false); failed.set(true); }} />}
    </View>
  </Window>;
}

mount(Workspace);
