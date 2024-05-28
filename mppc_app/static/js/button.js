function fetchLogDataAndFillTable() {
    $.getJSON('/_fetch_log', function(data) {
        // テーブルのtbodyを空にする
        $('#log-table tbody').empty();
        // 結果をテーブルに追加
        $.each(data.logs, function(index, log) {
            var row = $('<tr>');
            row.append($('<td>').text(log.time));
            row.append($('<td>').text(log.moduleId));
            row.append($('<td>').text(log.cmd_tx));
            row.append($('<td>').text(log.cmd_rx));
            row.append($('<td>').addClass(log.status).text(log.status));
            $('#log-table tbody').append(row);
        });
    }).fail(function() {
        alert('データの取得に失敗しました');
    });
}

// スイッチ
$(document).ready(function() {
    fetchLogDataAndFillTable();
    // 各スイッチに対して初期状態を設定
    $('.switch').each(function() {
        const switchElement = $(this);
        const moduleId = switchElement.data('module.id');
        const switchType = switchElement.data('switch.type');
 
        // 初期状態をサーバーから取得して設定
        $.getJSON('/_get_switch_status', { moduleId: moduleId, type: switchType }, function(data) {
            const initialState = data.state;
            const initialText  = data.text;
            if (initialState === 'on') {
                switchElement.addClass('on').removeClass('off').text(initialText);
            } else {
                switchElement.addClass('off').removeClass('on').text(initialText);
            }
        });

        switchElement.on('click', function() {
            // 現在のクラスが 'off' なら 'on' に変更する設定
            const isOff = switchElement.hasClass('off');
            const confirmMessage = "Module" + moduleId + ': ' +'Do you want to turn ' + (isOff ? 'on?' : 'off?');;
            // confirmMessage + (isOff ? 'on?' : 'off?');

            if (confirm(confirmMessage)) {
                $.getJSON('/_send_cmd', { moduleId: moduleId, cmdType: isOff ? 'on' : 'off' }, function(data) {
                    fetchLogDataAndFillTable();
                    if (data.isSuccess) {
                        switchElement.removeClass(isOff ? 'off' : 'on')
                                     .addClass(isOff ? 'on' : 'off')
                                     .text(switchType + ' ' + (isOff ? 'ON' : 'OFF'));
                    } else {
                        alert('Error: Failed');
                    }
                });
            }
        });
    });
});


// ボタン
$(document).ready(function() {
    // 全てのボタンに対してクリックイベントを設定
    $('button.status-button').on('click', function() {
        const moduleId = $(this).data('module.id');
        
        // 対応するテーブルのtbodyを特定する
        const tableBody = $('#module' +  moduleId + 'StatusTable tbody');
        
        // サーバーから初期状態を取得して設定
        $.getJSON('/_check_status', { moduleId: moduleId }, function(data) {
            // テーブルのtbodyを空にする
            tableBody.empty();
            
            // 結果をテーブルに追加
            $.each(data.detailStatus, function(index, status) {
                var row = $('<tr>');
                row.append($('<td>').text(status.label));
                row.append($('<td>').text(status.bit));
                row.append($('<td>').text(status.value));
                tableBody.append(row);
            });
        }).fail(function() {
            alert("Error: Fail to get data");
        });
    });


    // リセットしたらスイッチの状態確認して初期化を実行するようにしたいかも
    $('button.reset-button').on('click', function() {
        var moduleId = $(this).data('module.id');
        if (confirm("module" + moduleId + 'を再起動しますか？')) {
            $.getJSON('/_send_cmd', { moduleId: moduleId, cmdType: "reset" }, function(data) {
                fetchLogDataAndFillTable();
                if (!data.isSuccess) {
                    alert("Error: Fail to reset Module"+moduleId);
                }
            });
        }
    });
    
});

// フォーム関係
$(document).ready(function() {
    $('button.apply-button').on('click', function() {
        const moduleId = $(this).data('module.id');
        const hvType = $(this).data('hv.type');

        const hvForm = $('#module' + moduleId + hvType + 'HVForm');
        const hvValue = hvForm.val();

        if (hvValue === "") {
            alert('Error: Please input HV value');
            return;
        }

        if (confirm("Set HV of Module" + moduleId + ' to ' + hvValue + "?")) {
            $.getJSON('/_change_hv', { moduleId: moduleId, hvValue: hvValue, hvType: hvType }, function(data) {
                fetchLogDataAndFillTable();
                const statusCode = data.statusCode;
                
                switch (statusCode) {
                    case 0:
                        if (hvType == "Norm") { // 通常の電圧設定すると自動で温度補正がoffになる
                            $("#module"+ moduleId +"TempCorrSwitch").removeClass('on').addClass('off').text('Temp OFF');
                        } else if (hvType == "Temp") {
                            $("#module"+moduleId+"V0").text(hvValue);
                        }
                        break;
                    case 1:
                        alert('Error: Failed');
                        break;
                    case 2:
                        alert('Error: Out of Range');
                        break;
                    default:
                        alert('Error: Unknown Status Code');
                }
            });
        }
        hvForm.val('');
    });
});