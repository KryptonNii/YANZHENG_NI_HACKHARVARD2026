// The ONE import point for the shared contract (§5) in the web app.
// Until contracts/READY exists this re-exports A1's generated file via a local copy;
// then this line becomes `export * from "../contracts";` and _contracts_local.ts is deleted.
export * from "./_contracts_local";
