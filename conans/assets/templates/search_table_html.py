
content = """
<!DOCTYPE html>
<html lang="en">
    <head>
        <title>Conan | {{ search.reference }}</title>
        <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/v/dt/dt-1.10.20/datatables.min.css"/>
        <style>
            .cell_border_right {
                border-right: 1px dashed lightgrey;
            }
            tr td {
                white-space:nowrap;
            }
            tbody .monospaced {
                font-family: "Courier New", Courier, monospace;
                font-size: 80%;
            }
        </style>
    </head>
    <body>
        <h1>{{ search.reference }}</h1>
        <p>
            Depending on your package_id_mode, any combination of settings, options and requirements
            can give you a different packageID. Take into account that your configuration might be
            different from the one used to generate the packages.
        </p>

        <table id="example" class="display" style="width:100%">
            <thead>
                {%- set headers = results.get_headers(keys=['remote', 'package_id']) %}
                {%- set headers2rows = headers.row(n_rows=2) %}
                <tr>
                    {%- for category, subheaders in headers2rows %}
                        <th rowspan="{% if subheaders|length == 1 and not subheaders[0] %}2{% else %}1{% endif %}" colspan="{{ subheaders|length }}">
                            {{ category }}
                        </th>
                    {%- endfor %}
                </tr>
                <tr>
                    {%- for category, subheaders in headers2rows %}
                        {%- if subheaders|length != 1 or subheaders[0] != '' %}
                            {%- for subheader in subheaders %}
                                <th>{{ subheader|default(category, true) }}</th>
                            {%- endfor %}
                        {%- endif %}
                    {%- endfor %}
                </tr>
            </thead>
            <tbody>
                {%- for package in results.packages() %}
                    <tr>
                        {%- for item in package.row(headers) %}
                            <td>{{ item if item != None else ''}}</td>
                        {%- endfor %}
                    </tr>
                {%- endfor %}
            </tbody>
            <tfoot>
                <tr>
                    {%- for header in headers.row(n_rows=1) %}
                    <th>{{ header }}</th>
                    {%- endfor %}
                </tr>
            </tfoot>
        </table>

        <script type="text/javascript" src="https://code.jquery.com/jquery-3.3.1.js"></script>
        <script type="text/javascript" src="https://cdn.datatables.net/v/dt/dt-1.10.20/datatables.min.js"></script>
        <script>
            $(document).ready(function() {
                // Setup - add a text input to each footer cell
                $('#example tfoot th').each( function () {
                    var title = $(this).text();
                    $(this).html( '<input type="text" placeholder="Filter '+title+'" />' );
                });

                var table = $('#example').DataTable( {
                    "dom": "lrtip",
                    "lengthMenu": [[10, 25, 50, -1], [10, 25, 50, "All"]],
                    "pageLength": 10,
                    "columnDefs": [
                        { className: "cell_border_right", "targets": [ {{ headers.keys|length + headers.settings|length -1 }}, {{ headers.keys|length + headers.settings|length + headers.options|length -1 }}  ] },
                        { className: "cell_border_right monospaced", "targets": [{{ headers.keys|length -1 }}, ]}
                    ]
                });

                // Apply the search
                table.columns().every( function () {
                    var that = this;

                    $( 'input', this.footer() ).on( 'keyup change clear', function () {
                        if ( that.search() !== this.value ) {
                            that
                                .search( this.value )
                                .draw();
                        }
                    } );
                } );
            });
        </script>
    </body>
</html>
"""
