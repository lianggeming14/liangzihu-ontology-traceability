import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicBoolean;
import org.apache.jena.fuseki.main.FusekiServer;

/** Java 21 source-file entry; the stop channel is private to one deployment. */
class LocalFusekiRunner {
    public static void main(String[] args) throws Exception {
        if (args.length != 4) throw new IllegalArgumentException("config port stop-file deployment-id required");
        var server = FusekiServer.create().parseConfigFile(args[0]).port(Integer.parseInt(args[1]))
            .loopback(true).enableCors(false).build();
        var closed = new AtomicBoolean(false);
        Runnable stop = () -> {
            if (closed.compareAndSet(false, true)) {
                server.stop();
                server.getDataAccessPointRegistry().forEach((name, point) -> point.getDataService().shutdown());
            }
        };
        Runtime.getRuntime().addShutdownHook(new Thread(stop));
        server.start();
        System.out.println("local_fuseki_ready");
        var stopFile = Path.of(args[2]);
        while (!Files.isRegularFile(stopFile) || !Files.readString(stopFile).trim().equals(args[3])) {
            Thread.sleep(200);
        }
        stop.run();
        System.out.println("local_fuseki_stopped_cleanly");
    }
}
