import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const GITHUB_OWNER = "fouedhrv-ship-it";
const GITHUB_REPO = "domain-hunter";
const GITHUB_WORKFLOW = "workflow.yml";

Deno.serve(async (req: Request) => {
  // CORS
  if (req.method === "OPTIONS") {
    return new Response(null, {
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "authorization, content-type",
      },
    });
  }

  // Vérifier que l'utilisateur est connecté
  const authHeader = req.headers.get("Authorization");
  if (!authHeader) {
    return new Response(JSON.stringify({ error: "Non authentifié" }), {
      status: 401,
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
    });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_ANON_KEY")!,
    { global: { headers: { Authorization: authHeader } } }
  );

  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError || !user) {
    return new Response(JSON.stringify({ error: "Session invalide" }), {
      status: 401,
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
    });
  }

  // Déclencher le workflow GitHub Actions
  const githubToken = Deno.env.get("GITHUB_TOKEN");
  if (!githubToken) {
    return new Response(JSON.stringify({ error: "Token GitHub non configuré" }), {
      status: 500,
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
    });
  }

  const res = await fetch(
    `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${githubToken}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main" }),
    }
  );

  if (res.status === 204) {
    return new Response(JSON.stringify({ ok: true, message: "Scan lancé !" }), {
      status: 200,
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
    });
  }

  const body = await res.text();
  return new Response(JSON.stringify({ error: `GitHub ${res.status}: ${body}` }), {
    status: 500,
    headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
  });
});
