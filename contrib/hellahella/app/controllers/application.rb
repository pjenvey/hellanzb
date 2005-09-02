# The filters added to this controller will be run for all controllers in the application.
# Likewise will all the methods added be available for all controllers.
class ApplicationController < ActionController::Base
  
  require 'xmlrpc/client'
  
  private
  def authorize
    unless session[:user_id]
      flash[:notice] = "Please log in"
      session[:jumpto] = request.parameters
      redirect_to :controller => "login", :action => "login"
    end
  end
  
  def defaults
    @username = 'joe'
    @password = 'honker'
    @hnzb_server = '192.168.2.2'
    @hnzb_password = 'changeme'
    @hnzb_port = 8760
  end

  def load_queue
    @queue = server.call('list')
  end
  
  def load_status
    session[:status] ||= {:time => Time.now, :status => server.call("status")}
    if Time.now > session[:status][:time]
      session[:status] = {:time => Time.at(Time.now+6), :status => server.call("status")}
    end
    @status = session[:status][:status]
  end
  
  def server()
    @server ||= XMLRPC::Client.new(@hnzb_server, "/", @hnzb_port, nil, nil, "hellanzb", @hnzb_password)
  end
end