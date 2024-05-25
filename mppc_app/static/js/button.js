$(document).ready(function() {
    // 全てのボタンに対してクリックイベントを設定
    $('button.status-button').on('click', function() {
        var moduleId = $(this).data('module-id');
        
        // 対応するテーブルのtbodyを特定する
        var tableBody = $('#status-table-' + moduleId + ' tbody');
        
        // サーバーから初期状態を取得して設定
        $.getJSON('/_check_status', { module_id: moduleId }, function(data) {
            // テーブルのtbodyを空にする
            tableBody.empty();
            
            // 結果をテーブルに追加
            $.each(data.detail_status, function(index, status) {
                var row = $('<tr>');
                row.append($('<td>').text(status.label));
                row.append($('<td>').text(status.bit));
                row.append($('<td>').text(status.value));
                tableBody.append(row);
            });
        }).fail(function() {
            alert('データの取得に失敗しました');
        });
    });


    $('button.reset-button').on('click', function() {
        var moduleId = $(this).data('module-id');
        
        if (confirm("module" + moduleId + 'を再起動しますか？')) {
            $.getJSON($SCRIPT_ROOT + '/_send_cmd', { module_id: moduleId, cmd_type: "reset" }, function(data) {
                fetchLogDataAndFillTable();
                var is_success = data.is_success;
                if (!is_success) {
                    alert('失敗');
                }
            });
        }

    });
});