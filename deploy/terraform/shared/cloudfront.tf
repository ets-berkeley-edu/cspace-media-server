# The files distribution's function (D307): it only removes /<museum> from a file's path, /<museum>/objects/<sha256>
# -> /objects/<sha256>, the key in the museum's bucket (D195). No address rule: the signature is the gate, and a
# signature is issued only through the load balancer and its WAF.

resource "aws_cloudfront_function" "files" {
  name    = "${local.name}-files"
  comment = "Removes the museum from a file's path"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOT
    var FILE = /^\/(${join("|", local.museums)})(\/objects\/[0-9a-f]{64})$/;
    function handler(event) {
      var file = event.request.uri.match(FILE);
      if (file) event.request.uri = file[2];
      return event.request;
    }
  EOT
}
