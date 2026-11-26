import { open, test } from "nsh/test";

test("opens the local analysis workspace", async () => {
  const app = await open("./App.tsx");
  await app.waitFor("id:workspace-loaded", { timeout: 20000 });
});
