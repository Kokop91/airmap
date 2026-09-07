/**
 * Channel-occupancy bar charts (Plotly.js, loaded globally from the CDN
 * script tag in index.html -- no bundler, so `Plotly` is just a global).
 *
 * Two separate charts, not one combined chart: 2.4GHz (channels 1-13) and
 * 5GHz (channel numbers in the dozens-to-hundreds, non-contiguous) share no
 * useful x-axis scale, so overlaying them would make both unreadable.
 * 6GHz readings (rare; only newer Wi-Fi 6E gear) are intentionally excluded
 * from these two charts per the Phase 3 scope -- they still appear in the
 * networks table, just not charted here.
 */

const BANDS = [
  { band: "2.4GHz", elementId: "chart-2-4ghz", title: "Pasmo 2.4GHz" },
  { band: "5GHz", elementId: "chart-5ghz", title: "Pasmo 5GHz" },
];

function buildTrace(networks, band) {
  const ssidsByChannel = new Map();
  for (const network of networks) {
    if (network.band !== band) {
      continue;
    }
    const label = network.ssid || "(ukryta sieć)";
    if (!ssidsByChannel.has(network.channel)) {
      ssidsByChannel.set(network.channel, []);
    }
    ssidsByChannel.get(network.channel).push(label);
  }

  const channels = Array.from(ssidsByChannel.keys()).sort((a, b) => a - b);
  return {
    x: channels,
    y: channels.map((ch) => ssidsByChannel.get(ch).length),
    text: channels.map((ch) => ssidsByChannel.get(ch).join("<br>")),
    hovertemplate: "Kanał %{x}<br>%{y} sieci:<br>%{text}<extra></extra>",
    type: "bar",
    marker: { color: "#3a7bd5" },
  };
}

/** (Re-)draws both band charts from the current network list. */
export function renderChannelCharts(networks) {
  for (const { band, elementId, title } of BANDS) {
    Plotly.newPlot(
      elementId,
      [buildTrace(networks, band)],
      {
        title,
        xaxis: { title: "Kanał", dtick: 1 },
        yaxis: { title: "Liczba sieci", dtick: 1, rangemode: "tozero" },
        margin: { t: 40 },
      },
      { responsive: true, displayModeBar: false }
    );
  }
}
