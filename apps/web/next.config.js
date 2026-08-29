/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  // Tauri's Android asset loader resolves a flat `<route>.html` entrypoint
  // reliably, while nested `route/index.html` URLs can surface as a WebView
  // load error after an in-app navigation. Keep the export flat for the
  // packaged WebView; browser/server routing remains unchanged.
  trailingSlash: false,
  images: { unoptimized: true },
};
module.exports = nextConfig;
