// Run with node --test deploy/auth0/actions.test.js; no network or Auth0 account needed.
const test = require("node:test");
const assert = require("node:assert/strict");
const {onExecutePostLogin} = require("./post-login");
const {onExecuteCredentialsExchange} = require("./credentials-exchange");
const resource_server = {identifier: "https://portco-data-onboarding-api"};
function recorder() {
  const claims = {};
  const denied = [];
  return {claims, denied, access: {deny: (...args) => denied.push(args)},
    accessToken: {setCustomClaim: (k,v) => { claims[k] = v; }}};
}
test("untrusted user metadata cannot grant reviewer authority", async () => {
  const api = recorder();
  await onExecutePostLogin({resource_server, user: {user_metadata: {
    portco_role: "reviewer", portco_companies: ["portco_a"]}}}, api);
  assert.equal(api.denied.length, 1);
  assert.deepEqual(api.claims, {});
});
test("operator-assigned reviewer gets only explicit companies", async () => {
  const api = recorder();
  await onExecutePostLogin({resource_server, user: {app_metadata: {
    portco_role: "reviewer", portco_companies: ["portco_a", "portco_a"]}}}, api);
  assert.deepEqual(api.claims, {portco_role: "reviewer", portco_companies: ["portco_a"]});
});
test("wildcard tenants are denied", async () => {
  const api = recorder();
  await onExecutePostLogin({resource_server, user: {app_metadata: {
    portco_role: "reviewer", portco_companies: ["*"]}}}, api);
  assert.equal(api.denied.length, 1);
});
test("machine cannot promote itself to reviewer", async () => {
  const api = recorder();
  await onExecuteCredentialsExchange({resource_server, client: {metadata: {
    portco_role: "reviewer", portco_companies: '["portco_a"]'}}}, api);
  assert.deepEqual(api.claims, {portco_role: "agent", portco_companies: ["portco_a"]});
});
test("missing or malformed machine entitlements are denied", async () => {
  for (const metadata of [{}, {portco_companies: "bad-json"}, {portco_companies: '["*"]'}]) {
    const api = recorder();
    await onExecuteCredentialsExchange({resource_server, client: {metadata}}, api);
    assert.equal(api.denied.length, 1);
    assert.deepEqual(api.claims, {});
  }
});
test("actions never issue portfolio claims for a different API", async () => {
  const api = recorder();
  await onExecutePostLogin({resource_server: {identifier: "different-api"}}, api);
  await onExecuteCredentialsExchange({resource_server: {identifier: "different-api"}}, api);
  assert.deepEqual(api.claims, {});
});
