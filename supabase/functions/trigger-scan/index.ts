import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const GITHUB_OWNER = "fouedhrv-ship-it";
const GITHUB_REPO = "domain-hunter";
const GITHUB_WORKFLOW = "workflow.yml";

// Origines autorisées à appeler cette fonction. Avant : "*" (n'importe quel
// site pouvait tenter l'appel depuis le navigateur d'un utilisateur connecté,
// il lui suffisait d'avoir volé/intercepté un JWT valide). Restreint au seul
// domaine du dashboard déployé + localhost pour le dev.
const ALLOWED_ORIGINS = new Set([
  "https://domain-hunter-6cc.pages.dev",
  "http://localhost:5173",
]);

function corsHeaders(req: Request): Record<string, string> {
  const origin = req.headers.get("Origin") || "";
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.has(origin) ? origin : "",
    "Access-Control-Allow-Headers": "authorization, content-type",
    Vary: "Origin",
  };
}

Deno.serve(async (req: Request) => {
  const cors = corsHeaders(req);

  if (req.method === "OPTIONS") {
    return new Response(null, { headers: cors });
  }

  // Vérifier que l'utilisateur est connecté
  const authHeader = req.headers.get("Authorization");
  if (!authHeader) {
    return new Response(JSON.stringify({ error: "Non authentifié" }), {
      status: 401,
      headers: { "Content-Type": "application/json", ...cors },
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
      headers: { "Content-Type": "application/json", ...cors },
    });
  }

  // Déclencher le workflow GitHub Actions
  const githubToken = Deno.env.get("GITHUB_TOKEN");
  if (!githubToken) {
    return new Response(JSON.stringify({ error: "Token GitHub non configuré" }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...cors },
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
      headers: { "Content-Type": "application/json", ...cors },
    });
  }

  const body = await res.text();
  return new Response(JSON.stringify({ error: `GitHub ${res.status}: ${body}` }), {
    status: 500,
    headers: { "Content-Type": "application/json", ...cors },
  });
});
