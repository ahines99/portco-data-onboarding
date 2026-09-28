// Auth0 Machine-to-Machine Action. Machine clients can be agents, never reviewers.
exports.onExecuteCredentialsExchange = async (event, api) => {
  if (event.resource_server?.identifier !== "https://portco-data-onboarding-api") return;
  let companies;
  try {
    companies = JSON.parse(event.client.metadata?.portco_companies || "null");
  } catch (_) {
    api.access.deny("invalid_request", "Invalid portfolio application entitlement.");
    return;
  }
  if (!Array.isArray(companies) || companies.length < 1 || companies.length > 100 ||
      !companies.every(c => typeof c === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(c))) {
    api.access.deny("invalid_request", "No portfolio application entitlement is assigned.");
    return;
  }
  api.accessToken.setCustomClaim("portco_role", "agent");
  api.accessToken.setCustomClaim("portco_companies", [...new Set(companies)]);
};
