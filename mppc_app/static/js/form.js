$('button#cmd-form-button').bind('click', function() {
    $.ajax({
        url: '/_send',
        type: 'GET',
        data: {
            module_id: $('select[name="module-id"]').val(),
            cmd: $('input[name="cmd"]').val(),
            value: $('input[name="value"]').val()
        },
        success: function(response) {
            // テーブルのtbodyを空にする
            $('#log-table tbody').empty();
            // 結果をテーブルに追加
            $.each(response.results, function(index, result) {
                var row = $('<tr>');
                row.append($('<td>').text(result.module_id));
                row.append($('<td>').text(result.cmd_tx));
                row.append($('<td>').text(result.cmd_rx));
                // 列を追加する場合はここに追加
                $('#log-table tbody').append(row);
            });
        },
        error: function() {
            alert('データの取得に失敗しました');
        }
    });
    return false;
});