function fetchMppcDataAndPlot() {
    $.getJSON('/_fetch_mppc_data', function(data) {
        // データの設定
        var hv1   = { x: data.x, y: data.y[0], xaxis: 'x1', yaxis: 'y1', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '1', name: "V1 = " + (Math.round(data.y[0].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var curr1 = { x: data.x, y: data.y[1], xaxis: 'x1', yaxis: 'y1', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: '1', name: "I1 = " + (Math.round(data.y[1].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var temp1 = { x: data.x, y: data.y[2], xaxis: 'x1', yaxis: 'y1', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: '1', name: "T1 = " + (Math.round(data.y[2].slice(-1)[0]*100)/100).toString().padStart(5, ' ') };

        var hv2   = { x: data.x, y: data.y[3], xaxis: 'x2', yaxis: 'y2', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: "2", name: "V2 = " + (Math.round(data.y[3].slice(-1)[0]*100)/100).toString().padStart(5, ' ') };
        var curr2 = { x: data.x, y: data.y[4], xaxis: 'x2', yaxis: 'y2', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: "2", name: "I2 = " + (Math.round(data.y[4].slice(-1)[0]*100)/100).toString().padStart(5, ' ') };
        var temp2 = { x: data.x, y: data.y[5], xaxis: 'x2', yaxis: 'y2', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: "2", name: "T2 = " + (Math.round(data.y[5].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };

        var hv3   = { x: data.x, y: data.y[6], xaxis: 'x3', yaxis: 'y3', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '3', name: "V3 = " + (Math.round(data.y[6].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var curr3 = { x: data.x, y: data.y[7], xaxis: 'x3', yaxis: 'y3', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '3', name: "I3 = " + (Math.round(data.y[7].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var temp3 = { x: data.x, y: data.y[8], xaxis: 'x3', yaxis: 'y3', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: '3', name: "T3 = " + (Math.round(data.y[8].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };

        var hv4   = { x: data.x, y: data.y[9],  xaxis: 'x4', yaxis: 'y4', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '4', name: "V4 = " + (Math.round(data.y[9].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var curr4 = { x: data.x, y: data.y[10], xaxis: 'x4', yaxis: 'y4', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '4', name: "I4 = " + (Math.round(data.y[10].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var temp4 = { x: data.x, y: data.y[11], xaxis: 'x4', yaxis: 'y4', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: '4', name: "T4 = " + (Math.round(data.y[11].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };

        var trace = [hv1, temp1, curr1, hv2, temp2, curr2, hv3, temp3, curr3, hv4, temp4, curr4];

        var layout = {
            legend:{
                title: {
                    text: data.x.slice(-1)[0].toString().substring(0, 19).replace("T", " ") + "  (Unit; V [V], T [K], I [×10 mA])",
                    side: "top",
                    font:{
                        size: 18
                    },
                },
                x:0.5,
                y:1,
                xanchor:'center',
                yanchor:'bottom',
                orientation: "h",
                font:{
                    size: 18
                },
            },
            height: 800,
            grid: {rows: 2, columns: 2, pattern: 'independent'},
        };

        Plotly.newPlot('trendGraph', trace, layout);
    });
}

// ページロード時に実行
$(document).ready(function() {
    fetchMppcDataAndPlot();
    $.getJSON('/_get_interval_time', function(data) {
        const intervalTime = data.intervalTime * 1000;
        setInterval(fetchMppcDataAndPlot, intervalTime);
    });
});
