// Auth0 Login Action. Only administrator-owned app_metadata grants application access.
exports.onExecutePostLogin = async (event, api) => {
  if (event.resource_server?.identifier !== "https://portco-data-onboarding-api") return;
  const metadata = event.user.app_metadata || {};
  const role = metadata.portco_role;
  const companies = metadata.portco_companies;
  if (!["agent", "reviewer"].includes(role) || !Array.isArray(companies) ||
      companies.length < 1 || companies.length > 100 ||
      !companies.every(c => typeof c === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(c))) {
    api.access.deny("No portfolio application entitlement is assigned.");
    return;
  }
  api.accessToken.setCustomClaim("portco_role", role);
  api.accessToken.setCustomClaim("portco_companies", [...new Set(companies)]);
};
